import logging
from celery import shared_task

from app.services.authentication.auth_service import get_service_role_client
from app.services.study.concurrency import release_study_lock, clear_cooldown
from app.services.study.generator import generate_flashcards, generate_quiz
from app.services.study.flashcard_service import save_generated_flashcard_set
from app.services.study.quiz_service import save_generated_quiz

logger = logging.getLogger(__name__)


@shared_task(name="generate_study_tool_task", bind=True)
def generate_study_tool_task(
    self,
    notebook_id: str,
    user_id: str,
    source_id: str,
    tool_type: str,
    custom_prompt: str = None,
    requested_model: str = None,
    num_items: int = None
):
    """
    Asynchronous Celery background worker task for generating flashcards or quizzes.
    Runs non-blocking in the background so the user can continue using the application.
    """
    supabase = get_service_role_client()
    try:
        if tool_type == "flashcards":
            source_title, deck_data = generate_flashcards(
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
            logger.info(f"✅ Successfully generated flashcard set '{saved_set.get('id')}' for user {user_id}")
            return {"status": "completed", "tool_type": "flashcards", "id": saved_set.get("id")}

        elif tool_type == "quiz":
            source_title, quiz_data = generate_quiz(
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
            logger.info(f"✅ Successfully generated quiz '{saved_quiz.get('id')}' for user {user_id}")
            return {"status": "completed", "tool_type": "quiz", "id": saved_quiz.get("id")}

        else:
            raise ValueError(f"Unknown tool_type: {tool_type}")

    except Exception as e:
        logger.exception(f"❌ Background study generation task failed for user {user_id}: {e}")
        # Clear cooldown so user is not penalized for a failed run
        clear_cooldown(user_id, tool_type)
        raise e
    finally:
        # Always release the in-flight lock
        release_study_lock(user_id)
