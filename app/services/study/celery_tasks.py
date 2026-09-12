"""Celery Background Tasks for Study Artifact Generation.

Executes long-running study tool generation tasks (flashcard sets and practice
quizzes) asynchronously via worker processes to keep user interface responsive.
"""

import logging
from typing import Any, Dict, Optional

from celery import shared_task

from app.core.celery_app import celery_app
from app.services.authentication.auth_service import get_service_role_client
from app.services.study.concurrency import clear_cooldown, release_study_lock
from app.services.study.flashcard_service import save_generated_flashcard_set
from app.services.study.generator import generate_flashcards, generate_quiz
from app.services.study.quiz_service import save_generated_quiz

logger = logging.getLogger(__name__)


@shared_task(name="generate_study_tool_task", bind=True)
def generate_study_tool_task(
    self,
    notebook_id: str,
    user_id: str,
    source_id: str,
    tool_type: str,
    custom_prompt: Optional[str] = None,
    requested_model: Optional[str] = None,
    num_items: Optional[int] = None
) -> Dict[str, Any]:
    """Asynchronous Celery worker task for generating flashcards or quizzes.

    Runs in a worker process using elevated service-role credentials to generate
    and persist study tools. Automatically cleans up concurrency locks upon
    completion or exception, and clears user cooldowns if generation fails.

    Args:
        self: Celery Task execution instance (via bind=True).
        notebook_id: UUID of the notebook workspace.
        user_id: UUID of the requesting user.
        source_id: UUID of the source document to summarize or quiz on.
        tool_type: Artifact type to generate ('flashcards' or 'quiz').
        custom_prompt: Optional user instructions tailoring content focus.
        requested_model: Optional specific LLM model ID requested by user.
        num_items: Optional target number of questions or flashcards.

    Returns:
        Dictionary containing task outcome: 'status', 'tool_type', and created 'id'.

    Raises:
        ValueError: If tool_type is unrecognized.
        Exception: Propagates underlying generation or persistence failure after cleanup.
    """
    supabase = get_service_role_client()
    try:
        if tool_type == "flashcards":
            _, deck_data = generate_flashcards(
                supabase=supabase,
                user_id=user_id,
                source_id=source_id,
                custom_prompt=custom_prompt,
                num_items=num_items,
                requested_model=requested_model
            )
            saved_set = save_generated_flashcard_set(
                supabase=supabase,
                notebook_id=notebook_id,
                user_id=user_id,
                source_id=source_id,
                custom_prompt=custom_prompt,
                deck_data=deck_data
            )
            logger.info(f"Successfully generated flashcard set '{saved_set.get('id')}' for user {user_id}")
            return {"status": "completed", "tool_type": "flashcards", "id": saved_set.get("id")}

        elif tool_type == "quiz":
            _, quiz_data = generate_quiz(
                supabase=supabase,
                user_id=user_id,
                source_id=source_id,
                custom_prompt=custom_prompt,
                num_items=num_items,
                requested_model=requested_model
            )
            saved_quiz = save_generated_quiz(
                supabase=supabase,
                notebook_id=notebook_id,
                user_id=user_id,
                source_id=source_id,
                custom_prompt=custom_prompt,
                quiz_data=quiz_data
            )
            logger.info(f"Successfully generated quiz '{saved_quiz.get('id')}' for user {user_id}")
            return {"status": "completed", "tool_type": "quiz", "id": saved_quiz.get("id")}

        else:
            raise ValueError(f"Unknown tool_type: {tool_type}")

    except Exception as e:
        logger.exception(f"Background study generation task failed for user {user_id}: {e}")
        # Clear cooldown so user is not penalized for a failed run
        clear_cooldown(user_id, tool_type)
        raise e
    finally:
        # Always release the in-flight lock
        release_study_lock(user_id)
