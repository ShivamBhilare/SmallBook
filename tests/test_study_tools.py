import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
import json

from app.models.study_models import (
    StudyGenerateRequest,
    FlashcardSetGenerateSchema,
    FlashcardItemSchema,
    QuizGenerateSchema,
    QuizQuestionSchema,
    QuizOptionSchema,
    QuizAttemptSubmit,
    QuizAttemptResponse
)
from app.services.study.concurrency import acquire_study_lock, release_study_lock
from app.services.study.generator import generate_flashcards, generate_quiz
from app.services.study.quiz_service import grade_and_record_quiz_attempt


def test_study_models_validation():
    # 1. Test Flashcard schema validation
    fc_data = {
        "title": "Photosynthesis Concepts",
        "cards": [
            {
                "front_text": "What is chlorophyll?",
                "back_text": "The green pigment in plants that absorbs light energy.",
                "source_chunk_id": str(uuid4())
            }
        ]
    }
    deck = FlashcardSetGenerateSchema(**fc_data)
    assert deck.title == "Photosynthesis Concepts"
    assert len(deck.cards) == 1
    assert deck.cards[0].front_text == "What is chlorophyll?"

    # 2. Test Quiz schema validation
    quiz_data = {
        "title": "Cellular Respiration Quiz",
        "questions": [
            {
                "question_text": "Where does glycolysis occur in the cell?",
                "options": [
                    {"key": "A", "text": "Mitochondria"},
                    {"key": "B", "text": "Cytoplasm"},
                    {"key": "C", "text": "Nucleus"},
                    {"key": "D", "text": "Ribosome"}
                ],
                "correct_answer": "B",
                "explanation": "Glycolysis is the anaerobic breakdown of glucose occurring in the cytoplasm.",
                "source_chunk_id": str(uuid4())
            }
        ]
    }
    quiz = QuizGenerateSchema(**quiz_data)
    assert quiz.title == "Cellular Respiration Quiz"
    assert len(quiz.questions) == 1
    assert quiz.questions[0].correct_answer == "B"


def test_study_concurrency_lock():
    user_id = f"test-user-{uuid4()}"
    
    # 1. Acquire first lock -> must succeed
    acquired_1 = acquire_study_lock(user_id, timeout_seconds=10)
    assert acquired_1 is True

    # 2. Second parallel attempt for same user -> must fail
    acquired_2 = acquire_study_lock(user_id, timeout_seconds=10)
    assert acquired_2 is False

    # 3. Release lock
    release_study_lock(user_id)

    # 4. Now acquiring lock again -> must succeed
    acquired_3 = acquire_study_lock(user_id, timeout_seconds=10)
    assert acquired_3 is True
    release_study_lock(user_id)


def test_study_cooldown():
    from app.services.study.concurrency import check_and_set_cooldown, clear_cooldown
    user_id = f"cd-user-{uuid4()}"
    
    # 1. First run -> can generate
    can_gen, rem = check_and_set_cooldown(user_id, "flashcards", cooldown_seconds=1800)
    assert can_gen is True
    assert rem == 0

    # 2. Second run within 30 mins -> blocked with remaining seconds
    can_gen_2, rem_2 = check_and_set_cooldown(user_id, "flashcards", cooldown_seconds=1800)
    assert can_gen_2 is False
    assert rem_2 > 0

    # 3. Quiz is tracked independently from flashcards
    can_gen_quiz, rem_quiz = check_and_set_cooldown(user_id, "quiz", cooldown_seconds=1800)
    assert can_gen_quiz is True

    clear_cooldown(user_id, "flashcards")
    clear_cooldown(user_id, "quiz")


def test_generate_flashcards_service():
    mock_supabase = MagicMock()
    
    # Mock source fetch
    mock_supabase.table().select().eq().execute.side_effect = [
        MagicMock(data=[{"id": "s1", "original_filename": "Bio_Chapter1.pdf"}]), # source res
        MagicMock(data=[                                                        # chunks res
            {"id": "c1", "chunk_index": 0, "chunk_text": "Chloroplasts conduct photosynthesis."},
            {"id": "c2", "chunk_index": 1, "chunk_text": "ATP is the energy currency of the cell."}
        ]),
        MagicMock(data=[]) # preferences
    ]

    mock_llm_response = MagicMock()
    mock_llm_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({
                    "title": "Bio Chapter 1 Flashcards",
                    "cards": [
                        {
                            "front_text": "What is the function of chloroplasts?",
                            "back_text": "Conduct photosynthesis.",
                            "source_chunk_id": "c1"
                        }
                    ]
                })
            )
        )
    ]

    with patch("app.services.study.generator.completion", return_value=mock_llm_response):
        title, deck = generate_flashcards(
            supabase=mock_supabase,
            user_id="u1",
            source_id="s1",
            custom_prompt="Focus on cell biology",
            num_items=5
        )

        assert title == "Bio_Chapter1.pdf"
        assert deck.title == "Bio Chapter 1 Flashcards"
        assert len(deck.cards) == 1
        assert deck.cards[0].source_chunk_id == "c1"


def test_quiz_grading_logic():
    mock_supabase = MagicMock()
    quiz_id = str(uuid4())
    user_id = str(uuid4())
    q1_id = str(uuid4())
    q2_id = str(uuid4())

    mock_quiz_data = {
        "id": quiz_id,
        "title": "Math Quiz",
        "questions": [
            {
                "id": q1_id,
                "order_index": 0,
                "question_text": "2 + 2 = ?",
                "options": [{"key": "A", "text": "3"}, {"key": "B", "text": "4"}],
                "correct_answer": "B",
                "explanation": "2+2 equals 4"
            },
            {
                "id": q2_id,
                "order_index": 1,
                "question_text": "3 * 3 = ?",
                "options": [{"key": "A", "text": "9"}, {"key": "B", "text": "6"}],
                "correct_answer": "A",
                "explanation": "3*3 equals 9"
            }
        ]
    }

    with patch("app.services.study.quiz_service.get_quiz_with_questions", return_value=mock_quiz_data):
        # User answers Q1 correctly (B) and Q2 incorrectly (B)
        attempt = QuizAttemptSubmit(user_answers={q1_id: "B", q2_id: "B"})
        result = grade_and_record_quiz_attempt(mock_supabase, quiz_id, user_id, attempt)

        assert result.score == 1
        assert result.total_questions == 2
        assert result.percentage == 50.0
        assert result.results[0].is_correct is True
        assert result.results[1].is_correct is False
