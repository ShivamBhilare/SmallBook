"""Studio Tools Subsystem and Quiz Grading Test Suite for SmallBook.

Validates:
- Pydantic schema validation for flashcard decks and multiple-choice quizzes.
- Distributed concurrency locks preventing duplicate inflight generation per user.
- Cooldown clock tracking: 30-minute generation cooldowns per tool type with remaining time peeking.
- Flashcard generator service: Document chunk extraction and structured LLM completion.
- Practice quiz grading service: Instant option verification, score tallying, and percentage calculation.
- Number of items parameter propagation: Passing custom card/question counts to LLM prompts.
- Endpoint authorization: Enforcing ownership and notebook association for generation requests.
- Unified Studio artifact timeline: Sorting notes, flashcards, and quizzes by modified timestamp.
"""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.study_models import (
    FlashcardSetGenerateSchema,
    QuizAttemptSubmit,
    QuizGenerateSchema,
    StudyGenerateRequest,
)
from app.services.study.concurrency import acquire_study_lock, release_study_lock
from app.services.study.generator import generate_flashcards, generate_quiz
from app.services.study.quiz_service import grade_and_record_quiz_attempt


def test_study_models_validation():
    """Verifies that FlashcardSetGenerateSchema and QuizGenerateSchema validate structured JSON.

    Pattern:
        - Arrange: Sample dictionaries matching flashcard and quiz LLM generation schemas.
        - Act: Instantiate FlashcardSetGenerateSchema and QuizGenerateSchema.
        - Assert: Verify title, card front/back texts, options, and correct answers.
    """
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
    """Verifies that parallel generation requests for the same user are rejected by the lock.

    Pattern:
        - Arrange: Generate unique test user ID.
        - Act & Assert:
            1. First acquire succeeds (True).
            2. Second parallel acquire fails (False).
            3. Release lock.
            4. Re-acquiring succeeds (True).
    """
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
    """Verifies that generation cooldowns prevent repeated calls within the cooldown window.

    Pattern:
        - Arrange: Generate unique user ID.
        - Act & Assert:
            1. Initial check confirms 0s remaining.
            2. First generation sets cooldown and succeeds.
            3. Second generation within window fails with positive remaining seconds.
            4. Different tool type (quiz) is tracked on its own clock.
    """
    from app.services.study.concurrency import (
        check_and_set_cooldown,
        clear_cooldown,
        get_cooldown_remaining,
    )
    user_id = f"cd-user-{uuid4()}"
    
    # 0. Check remaining initially -> 0
    assert get_cooldown_remaining(user_id, "flashcards") == 0

    # 1. First run -> can generate
    can_gen, rem = check_and_set_cooldown(user_id, "flashcards", cooldown_seconds=1800)
    assert can_gen is True
    assert rem == 0

    # Remaining should now be positive without mutating
    assert get_cooldown_remaining(user_id, "flashcards") > 0

    # 2. Second run within 30 mins -> blocked with remaining seconds
    can_gen_2, rem_2 = check_and_set_cooldown(user_id, "flashcards", cooldown_seconds=1800)
    assert can_gen_2 is False
    assert rem_2 > 0

    # 3. Quiz is tracked independently from flashcards
    can_gen_quiz, _ = check_and_set_cooldown(user_id, "quiz", cooldown_seconds=1800)
    assert can_gen_quiz is True
    assert get_cooldown_remaining(user_id, "quiz") > 0

    clear_cooldown(user_id, "flashcards")
    clear_cooldown(user_id, "quiz")
    assert get_cooldown_remaining(user_id, "flashcards") == 0
    assert get_cooldown_remaining(user_id, "quiz") == 0


def test_study_cooldown_endpoint():
    """Verifies the GET /notebooks/{id}/study/cooldown status endpoint.

    Pattern:
        - Arrange: Mock user with unique ID.
        - Act & Assert:
            1. Check status initially: both flashcards and quiz active=False.
            2. Set flashcards cooldown.
            3. Query endpoint for flashcards: active=True, remaining_seconds > 0.
    """
    from app.routers.study import get_study_cooldown_status
    from app.services.study.concurrency import (
        check_and_set_cooldown,
        clear_cooldown,
    )

    user_id = f"endpoint-user-{uuid4()}"
    mock_user = MagicMock()
    mock_user.id = user_id

    # Initially both idle
    status_all = get_study_cooldown_status(notebook_id="nb-1", user=mock_user)
    assert status_all["flashcards"]["active"] is False
    assert status_all["quiz"]["active"] is False

    # Trigger flashcard cooldown
    check_and_set_cooldown(user_id, "flashcards", cooldown_seconds=1800)

    status_fc = get_study_cooldown_status(notebook_id="nb-1", tool_type="flashcards", user=mock_user)
    assert status_fc["active"] is True
    assert status_fc["remaining_seconds"] > 0
    assert status_fc["remaining_minutes"] >= 1

    clear_cooldown(user_id, "flashcards")


def test_generate_flashcards_service():
    """Verifies that generate_flashcards reads document chunks and parses LLM structured cards.

    Pattern:
        - Arrange: Mock Supabase queries returning source document and chunks, mock LLM response JSON.
        - Act: Call generate_flashcards.
        - Assert: Verify returned title, deck title, card count, and source_chunk_id.
    """
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
    """Verifies option comparison, scoring calculation, and question breakdown in quiz grading.

    Pattern:
        - Arrange: Mock quiz entity with 2 questions (answers: B, A).
        - Act: Submit user answers (Q1: B [correct], Q2: B [incorrect]).
        - Assert: Score=1, total=2, percentage=50.0%, and individual is_correct results are accurate.
    """
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


def test_generate_quiz_service_num_items():
    """Verifies that the requested num_items count is injected into the LLM system prompt.

    Pattern:
        - Arrange: Mock database queries and mock LiteLLM completion response.
        - Act: Call generate_quiz with num_items=7.
        - Assert: Verify '7 questions' appears in the prompt messages sent to LiteLLM.
    """
    mock_supabase = MagicMock()
    mock_supabase.table().select().eq().execute.side_effect = [
        MagicMock(data=[{"id": "s1", "original_filename": "Physics.pdf"}]),
        MagicMock(data=[
            {"id": "c1", "chunk_index": 0, "chunk_text": "Force equals mass times acceleration."}
        ]),
        MagicMock(data=[])
    ]

    mock_llm_response = MagicMock()
    mock_llm_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({
                    "title": "Physics Quiz",
                    "questions": [
                        {
                            "question_text": "What is Newton's Second Law?",
                            "options": [
                                {"key": "A", "text": "F = ma"},
                                {"key": "B", "text": "E = mc^2"},
                                {"key": "C", "text": "P = IV"},
                                {"key": "D", "text": "V = IR"}
                            ],
                            "correct_answer": "A",
                            "explanation": "F = ma relates force, mass, and acceleration.",
                            "source_chunk_id": "c1"
                        }
                    ]
                })
            )
        )
    ]

    with patch("app.services.study.generator.completion", return_value=mock_llm_response) as mock_comp:
        title, quiz = generate_quiz(
            supabase=mock_supabase,
            user_id="u1",
            source_id="s1",
            num_items=7
        )
        assert title == "Physics.pdf"
        assert len(quiz.questions) == 1
        call_kwargs = mock_comp.call_args[1]
        msgs = call_kwargs["messages"]
        assert "7 questions" in msgs[0]["content"]
        assert "7 questions" in msgs[1]["content"]


def test_generate_study_tool_endpoint_validations():
    """Verifies input validation and background task queuing on POST /notebooks/{id}/study/generate.

    Pattern:
        - Arrange: Mock ownership and association check matrices.
        - Act & Assert:
            1. Source not owned -> 404.
            2. Source not linked to notebook -> 400.
            3. Source owned and linked -> 202 Queued with background task registered.
    """
    from fastapi import HTTPException

    from app.routers.study import generate_study_tool

    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())
    source_id = str(uuid4())
    mock_bg = MagicMock()

    req = StudyGenerateRequest(source_id=source_id, tool_type="flashcards", num_items=5)

    # 1. Source not owned by user -> 404
    def side_effect_source_not_owned(table_name):
        mock_t = MagicMock()
        if table_name == "notebooks":
            mock_t.select().eq().eq().execute.return_value = MagicMock(data=[{"id": notebook_id}])
        elif table_name == "sources":
            mock_t.select().eq().eq().execute.return_value = MagicMock(data=[])  # Source not found/not owned
        return mock_t

    mock_client.table.side_effect = side_effect_source_not_owned
    with pytest.raises(HTTPException) as exc_404:
        generate_study_tool(notebook_id=notebook_id, payload=req, background_tasks=mock_bg, user=mock_user, client=mock_client)
    assert exc_404.value.status_code == 404

    # 2. Source not linked to notebook -> 400
    def side_effect_source_not_linked(table_name):
        mock_t = MagicMock()
        if table_name == "notebooks":
            mock_t.select().eq().eq().execute.return_value = MagicMock(data=[{"id": notebook_id}])
        elif table_name == "sources":
            mock_t.select().eq().eq().execute.return_value = MagicMock(data=[{"id": source_id}])  # Owned
        elif table_name == "notebook_sources":
            mock_t.select().eq().eq().execute.return_value = MagicMock(data=[])  # Not linked
        return mock_t

    mock_client.table.side_effect = side_effect_source_not_linked
    with pytest.raises(HTTPException) as exc_400:
        generate_study_tool(notebook_id=notebook_id, payload=req, background_tasks=mock_bg, user=mock_user, client=mock_client)
    assert exc_400.value.status_code == 400

    # 3. Source owned and linked -> 202 queued
    def side_effect_valid(table_name):
        mock_t = MagicMock()
        if table_name == "notebooks":
            mock_t.select().eq().eq().execute.return_value = MagicMock(data=[{"id": notebook_id}])
        elif table_name == "sources":
            mock_t.select().eq().eq().execute.return_value = MagicMock(data=[{"id": source_id}])
        elif table_name == "notebook_sources":
            mock_t.select().eq().eq().execute.return_value = MagicMock(data=[{"source_id": source_id}])
        return mock_t

    mock_client.table.side_effect = side_effect_valid
    with patch("app.routers.study.check_and_set_cooldown", return_value=(True, 0)), \
         patch("app.routers.study.acquire_study_lock", return_value=True):
        res = generate_study_tool(notebook_id=notebook_id, payload=req, background_tasks=mock_bg, user=mock_user, client=mock_client)
        assert res["status"] == "queued"
        assert mock_bg.add_task.called
        # Check num_items passed to background dispatcher
        bg_call_kwargs = mock_bg.add_task.call_args[1]
        assert bg_call_kwargs.get("num_items") == 5


def test_get_notebook_study_items_artifacts_sorting():
    """Verifies that get_notebook_study_items aggregates and sorts artifacts by modified timestamp.

    Pattern:
        - Arrange: Mock notes, flashcards, and quizzes with distinct created and updated timestamps.
        - Act: Call get_notebook_study_items.
        - Assert: Verify artifacts are sorted: note-1 (modified Sep 7), quiz-1 (Sep 6), deck-1 (Sep 5).
    """
    from app.routers.study import get_notebook_study_items

    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    mock_client = MagicMock()
    notebook_id = str(uuid4())

    mock_notes = [
        {
            "id": "note-1",
            "notebook_id": notebook_id,
            "title": "Ancient History Note",
            "content": "Notes content",
            "created_at": "2026-09-01T10:00:00Z",
            "updated_at": "2026-09-07T15:00:00Z"  # Most recently modified
        }
    ]
    mock_flashcards = [
        {
            "id": "deck-1",
            "notebook_id": notebook_id,
            "title": "Biology Terms",
            "cards_count": 10,
            "created_at": "2026-09-05T12:00:00Z",
            "updated_at": None
        }
    ]
    mock_quizzes = [
        {
            "id": "quiz-1",
            "notebook_id": notebook_id,
            "title": "Calculus Quiz",
            "questions_count": 5,
            "created_at": "2026-09-06T09:00:00Z",
            "updated_at": None
        }
    ]

    with patch("app.routers.study.list_notebook_notes", return_value=mock_notes), \
         patch("app.routers.study.list_notebook_flashcard_sets", return_value=mock_flashcards), \
         patch("app.routers.study.list_notebook_quizzes", return_value=mock_quizzes):

        res = get_notebook_study_items(notebook_id=notebook_id, user=mock_user, client=mock_client)

        assert "artifacts" in res
        assert len(res["artifacts"]) == 3

        # Ordering should be: note-1 (modified Sep 7), quiz-1 (created Sep 6), deck-1 (created Sep 5)
        assert res["artifacts"][0]["id"] == "note-1"
        assert res["artifacts"][0]["type"] == "note"

        assert res["artifacts"][1]["id"] == "quiz-1"
        assert res["artifacts"][1]["type"] == "quiz"

        assert res["artifacts"][2]["id"] == "deck-1"
        assert res["artifacts"][2]["type"] == "flashcards"
