import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4
import json

from app.routers.chat import send_chat_message
from app.models.chat_models import ChatRequestSchema


@pytest.mark.anyio
async def test_chat_streaming_does_not_save_empty_assistant_message_on_failure():
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())

    # User message save returns ID
    mock_user_msg_id = str(uuid4())
    mock_save_user = MagicMock(return_value={"id": mock_user_msg_id})
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
