import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from supabase import Client

from app.services.authentication.auth_service import login_required, get_supabase_client
from app.models.study_models import (
    StudyGenerateRequest,
    QuizAttemptSubmit,
    QuizAttemptResponse,
    NoteCreateRequest,
    NoteUpdateRequest,
    NoteResponse
)
from app.services.study.concurrency import (
    acquire_study_lock,
    release_study_lock,
    check_and_set_cooldown,
    clear_cooldown
)
from app.services.study.flashcard_service import (
    list_notebook_flashcard_sets,
    get_flashcard_set_with_cards,
    delete_flashcard_set
)
from app.services.study.quiz_service import (
    list_notebook_quizzes,
    get_quiz_with_questions,
    grade_and_record_quiz_attempt,
    delete_quiz
)
from app.services.study.note_service import (
    list_notebook_notes,
    get_note_by_id,
    create_note,
    update_note,
    delete_note
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Study Tools"])


def _dispatch_study_task(
    notebook_id: str,
    user_id: str,
    source_id: str,
    tool_type: str,
    custom_prompt: Optional[str],
    requested_model: Optional[str]
):
    """Dispatches generation task to Celery with fallback to direct execution."""
    try:
        from app.services.study.celery_tasks import generate_study_tool_task
        generate_study_tool_task.apply_async(
            args=[notebook_id, user_id, source_id, tool_type, custom_prompt, requested_model],
            connect_timeout=5,
            retry=True
        )
    except Exception as e:
        logger.warning(f"Celery dispatch failed ({e}). Executing directly in background worker thread...")
        try:
            from app.services.study.celery_tasks import generate_study_tool_task
            generate_study_tool_task.apply(
                args=[notebook_id, user_id, source_id, tool_type, custom_prompt, requested_model]
            )
        except Exception as direct_err:
            logger.exception(f"Direct background study task failed: {direct_err}")


# ==============================================================================
# GENERATION ENDPOINTS
# ==============================================================================

@router.post("/notebooks/{notebook_id}/study/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_study_tool(
    notebook_id: str,
    payload: StudyGenerateRequest,
    background_tasks: BackgroundTasks,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """
    Asynchronously generates a Flashcard deck or Quiz for a selected source document.
    Enforces:
      1. 30-minute cooldown (1 flashcard and 1 quiz per 30 minutes per user).
      2. Active generation lock.
      3. Non-blocking asynchronous Celery execution.
    """
    user_id = str(user.id)
    
    # 1. Verify notebook access
    nb_check = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user_id).execute()
    if not nb_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")

    # 2. Check 30-minute cooldown per user per tool type (1800s)
    can_generate, remaining_seconds = check_and_set_cooldown(user_id, payload.tool_type, cooldown_seconds=1800)
    if not can_generate:
        rem_mins = max(1, round(remaining_seconds / 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Cooldown active: You can generate 1 {payload.tool_type} every 30 minutes. Please wait {rem_mins} more minute(s)."
        )

    # 3. Acquire active generation lock
    if not acquire_study_lock(user_id, timeout_seconds=180):
        # Clear the cooldown we just set so user can try after current run finishes
        clear_cooldown(user_id, payload.tool_type)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A study tool is already being generated in the background. Please wait for it to complete."
        )

    # 4. Handoff to background Celery worker
    background_tasks.add_task(
        _dispatch_study_task,
        notebook_id=notebook_id,
        user_id=user_id,
        source_id=payload.source_id,
        tool_type=payload.tool_type,
        custom_prompt=payload.custom_prompt,
        requested_model=payload.model
    )

    return {
        "status": "queued",
        "tool_type": payload.tool_type,
        "message": f"Generating {payload.tool_type} in the background. You can continue using SmallBook."
    }


@router.get("/notebooks/{notebook_id}/study/items")
def get_notebook_study_items(
    notebook_id: str,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """
    Returns all generated flashcard decks, quizzes, and notes for a notebook to display in the Studio panel.
    """
    user_id = str(user.id)
    notes = list_notebook_notes(client, notebook_id, user_id)
    flashcard_sets = list_notebook_flashcard_sets(client, notebook_id, user_id)
    quizzes = list_notebook_quizzes(client, notebook_id, user_id)

    return {
        "notes": notes,
        "flashcard_sets": flashcard_sets,
        "quizzes": quizzes
    }


# ==============================================================================
# NOTE ENDPOINTS
# ==============================================================================

@router.get("/notebooks/{notebook_id}/notes")
def get_notebook_notes(
    notebook_id: str,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches all saved notes for a notebook."""
    user_id = str(user.id)
    return list_notebook_notes(client, notebook_id, user_id)


@router.post("/notebooks/{notebook_id}/notes", status_code=status.HTTP_201_CREATED)
def create_notebook_note(
    notebook_id: str,
    payload: NoteCreateRequest,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Creates a new note for a notebook (e.g. from chat response or manual input)."""
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
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches a specific note by ID."""
    note = get_note_by_id(client, note_id, str(user.id))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    return note


@router.put("/api/notes/{note_id}")
def update_note_endpoint(
    note_id: str,
    payload: NoteUpdateRequest,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Updates title or content of an existing note."""
    note = update_note(client, note_id, str(user.id), title=payload.title, content=payload.content)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found or update failed.")
    return note


@router.delete("/api/notes/{note_id}")
def delete_note_endpoint(
    note_id: str,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Deletes a note."""
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
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches a full flashcard deck with all cards."""
    deck = get_flashcard_set_with_cards(client, set_id, str(user.id))
    if not deck:
        raise HTTPException(status_code=404, detail="Flashcard deck not found.")
    return deck


@router.delete("/api/study/flashcards/{set_id}")
def delete_flashcard_deck(
    set_id: str,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Deletes a flashcard deck."""
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
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches a quiz with all questions."""
    quiz = get_quiz_with_questions(client, quiz_id, str(user.id))
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    return quiz


@router.post("/api/study/quizzes/{quiz_id}/submit", response_model=QuizAttemptResponse)
def submit_quiz_attempt(
    quiz_id: str,
    payload: QuizAttemptSubmit,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Submits user answers for a quiz, grades them, and saves the attempt."""
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
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Deletes a quiz."""
    success = delete_quiz(client, quiz_id, str(user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Quiz not found or delete failed.")
    return {"status": "success", "message": "Quiz deleted."}
