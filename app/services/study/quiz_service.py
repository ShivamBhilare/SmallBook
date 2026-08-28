import logging
from typing import List, Dict, Any, Optional
from supabase import Client
from postgrest.exceptions import APIError

from app.models.study_models import (
    QuizGenerateSchema,
    QuizResponse,
    QuizQuestionResponse,
    QuizAttemptSubmit,
    QuizAttemptResponse,
    QuestionResult
)

logger = logging.getLogger(__name__)


def list_notebook_quizzes(supabase: Client, notebook_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetches all quizzes for a given notebook with question counts."""
    try:
        res = (
            supabase.table("quizzes")
            .select("id, notebook_id, user_id, source_id, title, custom_prompt, created_at, updated_at")
            .eq("notebook_id", notebook_id)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        quizzes = res.data or []
        if not quizzes:
            return []

        # Count questions per quiz
        quiz_ids = [q["id"] for q in quizzes]
        questions_res = (
            supabase.table("quiz_questions")
            .select("quiz_id")
            .in_("quiz_id", quiz_ids)
            .execute()
        )
        questions_data = questions_res.data or []
        counts = {}
        for q in questions_data:
            qid = q["quiz_id"]
            counts[qid] = counts.get(qid, 0) + 1

        for q in quizzes:
            q["questions_count"] = counts.get(q["id"], 0)

        return quizzes
    except Exception as e:
        logger.error(f"Error fetching quizzes for notebook {notebook_id}: {e}")
        return []


def get_quiz_with_questions(supabase: Client, quiz_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a specific quiz and all its questions."""
    try:
        quiz_res = (
            supabase.table("quizzes")
            .select("*")
            .eq("id", quiz_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not quiz_res.data:
            return None
        quiz = quiz_res.data[0]

        questions_res = (
            supabase.table("quiz_questions")
            .select("*")
            .eq("quiz_id", quiz_id)
            .order("order_index", desc=False)
            .execute()
        )
        quiz["questions"] = questions_res.data or []
        quiz["questions_count"] = len(quiz["questions"])
        return quiz
    except Exception as e:
        logger.error(f"Error fetching quiz {quiz_id}: {e}")
        return None


def save_generated_quiz(
    supabase: Client,
    notebook_id: str,
    user_id: str,
    source_id: str,
    custom_prompt: Optional[str],
    quiz_data: QuizGenerateSchema
) -> Dict[str, Any]:
    """Persists a newly generated quiz and its questions to Supabase."""
    # 1. Insert Quiz
    quiz_payload = {
        "notebook_id": notebook_id,
        "user_id": user_id,
        "source_id": source_id,
        "title": quiz_data.title,
        "custom_prompt": custom_prompt
    }
    quiz_res = supabase.table("quizzes").insert(quiz_payload).execute()
    if not quiz_res.data:
        raise RuntimeError("Failed to create quiz record.")
    created_quiz = quiz_res.data[0]
    quiz_id = created_quiz["id"]

    # 2. Fetch valid chunk IDs for this source to ensure foreign key safety
    valid_chunk_ids = set()
    try:
        chunks_res = supabase.table("document_chunks").select("id").eq("source_id", source_id).execute()
        if chunks_res.data:
            valid_chunk_ids = {str(c["id"]) for c in chunks_res.data}
    except Exception as e:
        logger.warning(f"Could not verify chunk IDs for source {source_id}: {e}")

    # 3. Insert Questions in batch
    questions_payload = []
    for idx, q in enumerate(quiz_data.questions):
        raw_chunk_id = str(q.source_chunk_id) if q.source_chunk_id else None
        safe_chunk_id = raw_chunk_id if (raw_chunk_id and raw_chunk_id in valid_chunk_ids) else None

        questions_payload.append({
            "quiz_id": quiz_id,
            "order_index": idx,
            "question_text": q.question_text,
            "question_type": "multiple_choice",
            "options": [opt.model_dump() for opt in q.options],
            "correct_answer": q.correct_answer.strip().upper(),
            "explanation": q.explanation,
            "source_chunk_id": safe_chunk_id
        })

    if questions_payload:
        q_res = supabase.table("quiz_questions").insert(questions_payload).execute()
        created_quiz["questions"] = q_res.data or []
        created_quiz["questions_count"] = len(created_quiz["questions"])
    else:
        created_quiz["questions"] = []
        created_quiz["questions_count"] = 0

    return created_quiz


def grade_and_record_quiz_attempt(
    supabase: Client,
    quiz_id: str,
    user_id: str,
    attempt: QuizAttemptSubmit
) -> QuizAttemptResponse:
    """Grades user answers, calculates score, and records attempt in database."""
    quiz = get_quiz_with_questions(supabase, quiz_id, user_id)
    if not quiz:
        raise ValueError("Quiz not found.")

    questions = quiz.get("questions", [])
    total_questions = len(questions)
    if total_questions == 0:
        return QuizAttemptResponse(score=0, total_questions=0, percentage=0.0, results=[])

    score = 0
    results: List[QuestionResult] = []

    for q in questions:
        q_id = str(q["id"])
        order_idx = str(q.get("order_index", 0))
        correct_ans = str(q.get("correct_answer", "")).strip().upper()
        
        # User answer can be keyed by question ID or order index
        user_ans = (
            attempt.user_answers.get(q_id) 
            or attempt.user_answers.get(order_idx) 
            or ""
        ).strip().upper()

        is_correct = (user_ans == correct_ans) and bool(user_ans)
        if is_correct:
            score += 1

        results.append(QuestionResult(
            question_id=q_id,
            user_answer=user_ans if user_ans else None,
            correct_answer=correct_ans,
            is_correct=is_correct,
            explanation=q.get("explanation")
        ))

    percentage = round((score / total_questions) * 100, 1)

    # Persist attempt record
    try:
        supabase.table("quiz_attempts").insert({
            "quiz_id": quiz_id,
            "user_id": user_id,
            "score": score,
            "total_questions": total_questions,
            "user_answers": attempt.user_answers
        }).execute()
    except Exception as e:
        logger.warning(f"Could not record quiz attempt in DB (non-fatal): {e}")

    return QuizAttemptResponse(
        score=score,
        total_questions=total_questions,
        percentage=percentage,
        results=results
    )


def delete_quiz(supabase: Client, quiz_id: str, user_id: str) -> bool:
    """Deletes a quiz (cascade deletes child questions and attempts)."""
    try:
        res = (
            supabase.table("quizzes")
            .delete()
            .eq("id", quiz_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.error(f"Error deleting quiz {quiz_id}: {e}")
        return False
