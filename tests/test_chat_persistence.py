"""Chat Persistence and Streaming Invariant Tests for SmallBook.

Verifies:
- Streaming failure safety: Assistant message is never persisted with empty content on LLM failure,
  and metadata event yields message_id as None.
- Successful streaming completion: Assistant message and citation entities are correctly persisted,
  and final metadata payload emits the generated message_id.
- Metadata comment parsing: Embedded telemetry comments (timings_ms, used_tokens) are cleanly
  extracted and stripped from client-facing content.
"""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.chat_models import ChatRequestSchema
from app.routers.chat import send_chat_message


@pytest.mark.anyio
async def test_chat_streaming_does_not_save_empty_assistant_message_on_failure():
    """Verifies that an aborted or errored LLM stream does not persist an empty assistant message.

    Pattern:
        - Arrange: Mock Supabase client, user, and an LLM stream that yields an error event without tokens.
        - Act: Consume the async body_iterator returned by send_chat_message.
        - Assert: Verify save_chat_message was called only once (for user prompt), citations were not saved,
          and metadata event reflects message_id=None.
    """
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())

    # User message save returns ID
    mock_user_msg_id = str(uuid4())
    mock_save_assistant = MagicMock()
    mock_save_cit = MagicMock()

    payload = ChatRequestSchema(query="What is photosynthesis?")

    # LLM yields an error event or aborts without chunk tokens
    def mock_llm_stream(*args, **kwargs):
        yield ("error", "RateLimitError: 429 Too Many Requests")

    with patch("app.routers.chat.save_chat_message", side_effect=[{"id": mock_user_msg_id}, mock_save_assistant]) as mock_save, \
         patch("app.routers.chat.save_citations", mock_save_cit), \
         patch("app.routers.chat.retrieve_multi", return_value={"selected_parents": [], "used_tokens": 0}), \
         patch("app.routers.chat.stream_resilient_llm_response", side_effect=mock_llm_stream), \
         patch("app.routers.chat.get_user_preferences", return_value={"active_model": "groq/openai/gpt-oss-120b"}), \
         patch("app.routers.chat.get_decrypted_user_key", return_value={"api_key": "test_key", "api_base": None}):

        streaming_response = send_chat_message(
            notebook_id=notebook_id,
            payload=payload,
            user=mock_user,
            client=mock_client
        )

        # Consume the async generator
        events = [chunk async for chunk in streaming_response.body_iterator]
        assert len(events) > 0

        # Verify only user message was saved (called once), assistant message was NOT saved
        assert mock_save.call_count == 1
        user_save_call = mock_save.call_args_list[0]
        assert user_save_call[1]["role"] == "user"

        # Verify citations were not saved
        assert not mock_save_cit.called

        # Verify metadata yielded message_id as None
        metadata_events = [e for e in events if '"type": "metadata"' in e]
        assert len(metadata_events) == 1
        meta_data = json.loads(metadata_events[0].replace("data: ", "").strip())
        assert meta_data["message_id"] is None


@pytest.mark.anyio
async def test_chat_streaming_saves_assistant_message_when_content_generated():
    """Verifies that assistant message and grounding citations are persisted upon successful generation.

    Pattern:
        - Arrange: Mock dependencies with an LLM stream returning text chunks and parent document citations.
        - Act: Consume the async body_iterator from send_chat_message.
        - Assert: Verify save_chat_message called twice (user and assistant), full response content persisted,
          citations saved, and metadata event contains the saved assistant message ID.
    """
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())
    mock_user_msg_id = str(uuid4())
    mock_asst_msg_id = str(uuid4())

    src_id = str(uuid4())
    payload = ChatRequestSchema(query="What is photosynthesis?", source_ids=[src_id])

    def mock_llm_stream(*args, **kwargs):
        yield ("used_model", "groq/openai/gpt-oss-120b")
        yield ("chunk", "Photosynthesis is the process ")
        yield ("chunk", "by which plants make food.")

    mock_chunk = MagicMock()
    mock_chunk.id = str(uuid4())
    mock_chunk.document_id = src_id
    mock_chunk.text = "Photosynthesis background info"
    mock_chunk.order = 0
    mock_chunk.score = 0.95

    with patch("app.routers.chat.save_chat_message", side_effect=[{"id": mock_user_msg_id}, {"id": mock_asst_msg_id}]) as mock_save, \
         patch("app.routers.chat.save_citations") as mock_save_cit, \
         patch("app.routers.chat.get_notebook_sources", return_value=[{"id": src_id, "original_filename": "Bio.pdf"}]), \
         patch("app.routers.chat.retrieve_multi", return_value={"selected_parents": [mock_chunk], "used_tokens": 50}), \
         patch("app.routers.chat.stream_resilient_llm_response", side_effect=mock_llm_stream), \
         patch("app.routers.chat.get_user_preferences", return_value={"active_model": "groq/openai/gpt-oss-120b"}), \
         patch("app.routers.chat.get_decrypted_user_key", return_value={"api_key": "test_key", "api_base": None}):

        streaming_response = send_chat_message(
            notebook_id=notebook_id,
            payload=payload,
            user=mock_user,
            client=mock_client
        )

        events = [chunk async for chunk in streaming_response.body_iterator]
        assert len(events) > 0

        # User message AND assistant message saved (called twice)
        assert mock_save.call_count == 2
        asst_save_call = mock_save.call_args_list[1]
        assert asst_save_call[1]["role"] == "assistant"
        assert asst_save_call[1]["content"] == "Photosynthesis is the process by which plants make food."

        # Citations saved
        assert mock_save_cit.called

        # Metadata yielded with saved assistant message ID
        metadata_events = [e for e in events if '"type": "metadata"' in e]
        assert len(metadata_events) == 1
        meta_data = json.loads(metadata_events[0].replace("data: ", "").strip())
        assert meta_data["message_id"] == mock_asst_msg_id


def test_chat_history_metadata_extraction():
    """Tests metadata comment parsing and sanitization from stored message records.

    Pattern:
        - Arrange: Prepare sample response strings with and without embedded HTML comments.
        - Act: Execute extract_message_metadata and get_chat_history with mocked database records.
        - Assert: Verify metadata dictionary is parsed and clean message text is returned.
    """
    from app.services.chat.chat_service import extract_message_metadata, get_chat_history

    raw_text = "Here is the response.\n\n<!--smallbook-meta:{\"timings_ms\": {\"total_ms\": 123.4, \"retrieval_ms\": 23.4, \"llm_ms\": 100.0}, \"used_tokens\": 250}-->"
    clean, meta = extract_message_metadata(raw_text)
    assert clean == "Here is the response."
    assert meta["timings_ms"]["total_ms"] == 123.4
    assert meta["used_tokens"] == 250

    # Test clean text without metadata
    clean2, meta2 = extract_message_metadata("Plain answer without metadata")
    assert clean2 == "Plain answer without metadata"
    assert meta2 is None

    # Test get_chat_history parsing
    mock_client = MagicMock()
    mock_client.table().select().eq().order().execute.return_value = MagicMock(
        data=[
            {
                "id": "msg-1",
                "notebook_id": "nb-1",
                "role": "assistant",
                "content": raw_text,
                "created_at": "2026-09-09T00:00:00Z"
            }
        ]
    )
    mock_client.table().select().in_().order().execute.return_value = MagicMock(data=[])

    history = get_chat_history(mock_client, "nb-1")
    assert len(history) == 1
    assert history[0]["content"] == "Here is the response."
    assert history[0]["timings_ms"]["total_ms"] == 123.4
    assert history[0]["used_tokens"] == 250
