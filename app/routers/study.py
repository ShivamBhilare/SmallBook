"""Study Tools Router Module.

Exposes RESTful endpoints for generating AI-driven study tools (flashcard decks
and multiple-choice practice quizzes), querying tool cooldowns, managing Markdown
notes, scoring quiz submissions, and retrieving aggregated Studio artifacts.
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from supabase import Client

from app.core.redis_client import get_redis_client
from app.models.study_models import (
    NoteCreateRequest,
    NoteUpdateRequest,
    QuizAttemptResponse,
    QuizAttemptSubmit,
    StudyGenerateRequest,
)
from app.services.authentication.auth_service import get_supabase_client, login_required
from app.services.study.concurrency import (
    acquire_study_lock,
    check_and_set_cooldown,
    clear_cooldown,
    get_cooldown_remaining,
)
from app.services.study.flashcard_service import (
    delete_flashcard_set,
    get_flashcard_set_with_cards,
    list_notebook_flashcard_sets,
)
from app.services.study.note_service import (
    create_note,
    delete_note,
    get_note_by_id,
    list_notebook_notes,
    update_note,
)
from app.services.study.quiz_service import (
    delete_quiz,
    get_quiz_with_questions,
    grade_and_record_quiz_attempt,
    list_notebook_quizzes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Study Tools"])


def _dispatch_study_task(
    notebook_id: str,
    user_id: str,
    source_id: str,
    tool_type: str,
    custom_prompt: Optional[str],
    requested_model: Optional[str],
    num_items: Optional[int] = None
):
    """Dispatches study generation task to Celery with background thread fallback.

    Tries dispatching to Celery broker with a 2-second connection timeout. If Celery
    is unavailable (e.g. in local development without active workers), falls back to a
    daemonized background thread.

    Args:
        notebook_id: UUID of the notebook workspace.
        user_id: UUID of the requesting user.
        source_id: UUID of the source document.
        tool_type: Tool type ('flashcards' or 'quiz').
        custom_prompt: Optional custom generation prompt or focus topics.
        requested_model: Optional specific LLM model ID.
        num_items: Target number of items to generate.
    """
    redis_client = get_redis_client()
    if redis_client:
        try:
            from app.services.study.celery_tasks import generate_study_tool_task
            generate_study_tool_task.apply_async(
                args=[notebook_id, user_id, source_id, tool_type, custom_prompt, requested_model, num_items],
                connect_timeout=2,
                retry=False
            )
            return
        except Exception as e:
            logger.warning(f"Celery dispatch failed ({e}). Executing directly in background worker thread...")

    # Detached daemon thread so it runs in background without blocking Celery retries or FastAPI worker
    import threading
    from app.services.study.celery_tasks import generate_study_tool_task

    def _run_in_background():
        try:
            generate_study_tool_task.apply(
                args=[notebook_id, user_id, source_id, tool_type, custom_prompt, requested_model, num_items]
            )
        except Exception as direct_err:
            logger.exception(f"Direct background study task failed: {direct_err}")

    thread = threading.Thread(target=_run_in_background, daemon=True)
    thread.start()


# ==============================================================================
# GENERATION ENDPOINTS
# ==============================================================================


@router.get("/notebooks/{notebook_id}/study/cooldown")
def get_study_cooldown_status(
    notebook_id: str,
    tool_type: Optional[str] = None,
    user=Depends(login_required)
):
    """Returns remaining cooldown time for study tools without mutating timers.

    Args:
        notebook_id: UUID of the notebook.
        tool_type: Optional tool filter ('flashcards' or 'quiz').
        user: Authenticated user object from dependency.

    Returns:
        Dictionary containing cooldown status, remaining seconds, and minutes.
    """
    user_id = str(user.id)
    rem_fc = get_cooldown_remaining(user_id, "flashcards")
    rem_quiz = get_cooldown_remaining(user_id, "quiz")

    if tool_type:
        rem = rem_fc if tool_type == "flashcards" else rem_quiz
        return {
            "tool_type": tool_type,
            "active": rem > 0,
            "remaining_seconds": rem,
            "remaining_minutes": max(1, round(rem / 60)) if rem > 0 else 0
        }

    return {
        "flashcards": {
            "active": rem_fc > 0,
            "remaining_seconds": rem_fc,
            "remaining_minutes": max(1, round(rem_fc / 60)) if rem_fc > 0 else 0
        },
        "quiz": {
            "active": rem_quiz > 0,
            "remaining_seconds": rem_quiz,
            "remaining_minutes": max(1, round(rem_quiz / 60)) if rem_quiz > 0 else 0
        }
    }


@router.post("/notebooks/{notebook_id}/study/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_study_tool(
    notebook_id: str,
    payload: StudyGenerateRequest,
    background_tasks: BackgroundTasks,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Enqueues asynchronous background generation for a flashcard deck or quiz.

    Enforces:
      1. Immediate fast-path 30-minute cooldown check (zero database latency).
      2. Notebook and source document ownership verification.
      3. Active concurrent generation locking.
      4. Asynchronous worker task dispatch.

    Args:
        notebook_id: UUID of the notebook workspace.
        payload: StudyGenerateRequest with tool_type, source_id, prompt, model, count.
        background_tasks: FastAPI background task manager.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary with status 'queued' and confirmation message.

    Raises:
        HTTPException: 400 if source not linked; 404 if notebook/source missing; 429 if rate-limited or locked.
    """
    user_id = str(user.id)

    # 1. IMMEDIATE FAST-PATH: Check 30-minute cooldown per user per tool type (1800s)
    # Checked FIRST to return 429 in 0ms without waiting for 3 database queries!
    rem = get_cooldown_remaining(user_id, payload.tool_type)
    if rem > 0:
        rem_mins = max(1, round(rem / 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Cooldown active: You can generate 1 {payload.tool_type} every 30 minutes. Please wait {rem_mins} more minute(s)."
        )

    # 2. Verify notebook access
    nb_check = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user_id).execute()
    if not nb_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")

    # 3. Verify source access and that source is attached to this notebook
    source_check = client.table("sources").select("id").eq("id", payload.source_id).eq("user_id", user_id).execute()
    if not source_check.data:
        raise HTTPException(status_code=404, detail="Source document not found or access denied.")

    link_check = client.table("notebook_sources").select("source_id").eq("notebook_id", notebook_id).eq("source_id", payload.source_id).execute()
    if not link_check.data:
        raise HTTPException(status_code=400, detail="Source document is not linked to this notebook.")

    # 4. Set cooldown atomically
    can_generate, remaining_seconds = check_and_set_cooldown(user_id, payload.tool_type, cooldown_seconds=1800)
    if not can_generate:
        rem_mins = max(1, round(remaining_seconds / 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Cooldown active: You can generate 1 {payload.tool_type} every 30 minutes. Please wait {rem_mins} more minute(s)."
        )

    # 5. Acquire active generation lock
    if not acquire_study_lock(user_id, timeout_seconds=180):
        # Clear the cooldown we just set so user can try after current run finishes
        clear_cooldown(user_id, payload.tool_type)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A study tool is already being generated in the background. Please wait for it to complete."
        )

    # 6. Handoff to background Celery / thread worker
    background_tasks.add_task(
        _dispatch_study_task,
        notebook_id=notebook_id,
        user_id=user_id,
        source_id=payload.source_id,
        tool_type=payload.tool_type,
        custom_prompt=payload.custom_prompt,
        requested_model=payload.model,
        num_items=payload.num_items
    )

    return {
        "status": "queued",
        "tool_type": payload.tool_type,
        "message": f"Generating {payload.tool_type} in the background. You can continue using SmallBook."
    }


@router.get("/notebooks/{notebook_id}/study/items")
def get_notebook_study_items(
    notebook_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Returns all flashcard decks, practice quizzes, and notes for the Studio panel.

    Combines study artifacts into a chronological unified timeline.

    Args:
        notebook_id: UUID of the notebook workspace.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing 'notes', 'flashcard_sets', 'quizzes', and unified 'artifacts'.
    """
    user_id = str(user.id)
    notes = list_notebook_notes(client, notebook_id, user_id)
    flashcard_sets = list_notebook_flashcard_sets(client, notebook_id, user_id)
    quizzes = list_notebook_quizzes(client, notebook_id, user_id)

    # Build unified artifacts list sorted by date of creation/modification (descending)
    artifacts = []
    for n in notes:
        artifacts.append({
            "type": "note",
            "id": n["id"],
            "title": n.get("title") or "Untitled Note",
            "created_at": n.get("created_at"),
            "updated_at": n.get("updated_at"),
            "content": n.get("content", ""),
            "raw": n
        })
    for f in flashcard_sets:
        artifacts.append({
            "type": "flashcards",
            "id": f["id"],
            "title": f.get("title") or "Flashcards",
            "cards_count": f.get("cards_count", 0),
            "created_at": f.get("created_at"),
            "updated_at": f.get("updated_at"),
            "raw": f
        })
    for q in quizzes:
        artifacts.append({
            "type": "quiz",
            "id": q["id"],
            "title": q.get("title") or "Practice Quiz",
            "questions_count": q.get("questions_count", 0),
            "created_at": q.get("created_at"),
            "updated_at": q.get("updated_at"),
            "raw": q
        })

    # Sort descending by modification date, falling back to creation date
    artifacts.sort(
        key=lambda a: a.get("updated_at") or a.get("created_at") or "",
        reverse=True
    )

    return {
        "notes": notes,
        "flashcard_sets": flashcard_sets,
        "quizzes": quizzes,
        "artifacts": artifacts
    }


# ==============================================================================
# NOTE ENDPOINTS
# ==============================================================================


@router.get("/notebooks/{notebook_id}/notes")
def get_notebook_notes(
    notebook_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches all saved notes for a specific notebook.

    Args:
        notebook_id: UUID of the notebook workspace.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        List of note objects.
    """
    user_id = str(user.id)
    return list_notebook_notes(client, notebook_id, user_id)


@router.post("/notebooks/{notebook_id}/notes", status_code=status.HTTP_201_CREATED)
def create_notebook_note(
    notebook_id: str,
    payload: NoteCreateRequest,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Creates a new note associated with a notebook workspace.

    Args:
        notebook_id: UUID of the notebook workspace.
        payload: NoteCreateRequest with title, content, and optional source_message_id.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Created note dictionary with HTTP 201 status.

    Raises:
        HTTPException: 500 if database creation fails.
    """
    user_id = str(user.id)
    try:
        note = create_note(
            client,
            notebook_id=notebook_id,
            user_id=user_id,
            title=payload.title,
            content=payload.content,
            source_message_id=payload.source_message_id
        )
        return note
    except Exception as e:
        logger.exception(f"Error creating note: {e}")
        raise HTTPException(status_code=500, detail="Failed to create note.")


@router.get("/api/notes/{note_id}")
def get_note_endpoint(
    note_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches a specific note by ID.

    Args:
        note_id: UUID of the note.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Note dictionary.

    Raises:
        HTTPException: 404 if not found or unauthorized.
    """
    note = get_note_by_id(client, note_id, str(user.id))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    return note


@router.put("/api/notes/{note_id}")
def update_note_endpoint(
    note_id: str,
    payload: NoteUpdateRequest,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Updates title and/or content of an existing note.

    Args:
        note_id: UUID of the note to update.
        payload: NoteUpdateRequest with optional title or content.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Updated note dictionary.

    Raises:
        HTTPException: 404 if note not found or update fails.
    """
    note = update_note(client, note_id, str(user.id), title=payload.title, content=payload.content)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found or update failed.")
    return note


@router.delete("/api/notes/{note_id}")
def delete_note_endpoint(
    note_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Deletes a note.

    Args:
        note_id: UUID of the note to delete.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary with status and deletion message.

    Raises:
        HTTPException: 404 if note not found or deletion fails.
    """
    success = delete_note(client, note_id, str(user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Note not found or delete failed.")
    return {"status": "success", "message": "Note deleted."}


# ==============================================================================
# FLASHCARD ENDPOINTS
# ==============================================================================


@router.get("/api/study/flashcards/{set_id}")
def get_flashcard_deck(
    set_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches a full flashcard deck with its child cards.

    Args:
        set_id: UUID of the flashcard deck.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Deck dictionary containing cards array.

    Raises:
        HTTPException: 404 if deck not found.
    """
    deck = get_flashcard_set_with_cards(client, set_id, str(user.id))
    if not deck:
        raise HTTPException(status_code=404, detail="Flashcard deck not found.")
    return deck


@router.delete("/api/study/flashcards/{set_id}")
def delete_flashcard_deck(
    set_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Deletes a flashcard deck and cascades removal of child cards.

    Args:
        set_id: UUID of the flashcard deck.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary confirming deck deletion.

    Raises:
        HTTPException: 404 if deck not found.
    """
    success = delete_flashcard_set(client, set_id, str(user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Flashcard deck not found or delete failed.")
    return {"status": "success", "message": "Flashcard deck deleted."}


# ==============================================================================
# QUIZ ENDPOINTS
# ==============================================================================


@router.get("/api/study/quizzes/{quiz_id}")
def get_quiz(
    quiz_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches a practice quiz and all its multiple-choice questions.

    Args:
        quiz_id: UUID of the quiz.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Quiz dictionary containing questions array.

    Raises:
        HTTPException: 404 if quiz not found.
    """
    quiz = get_quiz_with_questions(client, quiz_id, str(user.id))
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    return quiz


@router.post("/api/study/quizzes/{quiz_id}/submit", response_model=QuizAttemptResponse)
def submit_quiz_attempt(
    quiz_id: str,
    payload: QuizAttemptSubmit,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Grades submitted quiz answers, calculates percentage score, and records attempt.

    Args:
        quiz_id: UUID of the quiz.
        payload: QuizAttemptSubmit containing mapping of question answers.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        QuizAttemptResponse detailing total score, percentage, and per-question breakdowns.

    Raises:
        HTTPException: 404 if quiz not found; 500 on grading or logging error.
    """
    try:
        return grade_and_record_quiz_attempt(client, quiz_id, str(user.id), payload)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Quiz grading error: {e}")
        raise HTTPException(status_code=500, detail="Failed to grade quiz attempt.")


@router.delete("/api/study/quizzes/{quiz_id}")
def delete_quiz_endpoint(
    quiz_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Deletes a practice quiz and cascades removal of questions and attempts.

    Args:
        quiz_id: UUID of the quiz to delete.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary confirming quiz deletion.

    Raises:
        HTTPException: 404 if quiz not found.
    """
    success = delete_quiz(client, quiz_id, str(user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Quiz not found or delete failed.")
    return {"status": "success", "message": "Quiz deleted."}
