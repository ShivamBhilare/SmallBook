"""Cascading Fallback Resiliency Tests for SmallBook RAG Prompt Pipeline.

Verifies:
- Direct primary model execution when healthy (emitting used_model and chunk events).
- Graceful provider failover when primary model throws RateLimitError (429),
  dispatching a fallback_notice event and succeeding on secondary free-tier provider.
"""

from unittest.mock import MagicMock, patch

from app.services.rag.promptllm import stream_resilient_llm_response


def test_resilient_stream_primary_success():
    """Tests that a healthy primary LLM model streams chunks without triggering fallback.

    Pattern:
        - Arrange: Mock LiteLLM completion returning two sequential text chunks ('Hello ', 'world!').
        - Act: Consume the stream_resilient_llm_response generator into a list of events.
        - Assert: Verify events contain 'used_model' and 'chunk', and concatenated content equals 'Hello world!'.
    """
    mock_chunk_1 = MagicMock()
    mock_chunk_1.choices = [MagicMock(delta=MagicMock(content="Hello "))]
    mock_chunk_2 = MagicMock()
    mock_chunk_2.choices = [MagicMock(delta=MagicMock(content="world!"))]

    with patch("app.services.rag.promptllm.completion", return_value=[mock_chunk_1, mock_chunk_2]):
        events = list(stream_resilient_llm_response(
            prompt="Hello",
            system_instruction="Test instruction",
            requested_model="groq/openai/gpt-oss-120b",
            user_primary_key="test_key",
            fallback_enabled=True
        ))

        types = [e[0] for e in events]
        assert "used_model" in types
        assert "chunk" in types
        
        content = "".join([e[1] for e in events if e[0] == "chunk"])
        assert content == "Hello world!"


def test_resilient_stream_fallback_on_primary_failure():
    """Tests automatic fallback cascade when primary model encounters a RateLimitError (429).

    Pattern:
        - Arrange: Mock completion to throw 429 on first invocation and succeed with mock_chunk on second;
          mock developer API keys for fallback providers.
        - Act: Consume stream_resilient_llm_response generator.
        - Assert: Verify 'fallback_notice' event is emitted containing original_model='gpt-4o'
          and error explanation, followed by completed chunk content from fallback provider.
    """
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock(delta=MagicMock(content="Fallback answer"))]

    call_count = 0
    def mock_completion(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("RateLimitError: 429 Too Many Requests")
        return [mock_chunk]

    with patch("app.services.rag.promptllm.completion", side_effect=mock_completion), \
         patch("app.services.rag.promptllm.get_developer_gemini_key", return_value="gemini_dev_key"), \
         patch("app.services.rag.promptllm.get_developer_groq_key", return_value="groq_dev_key"):
        
        events = list(stream_resilient_llm_response(
            prompt="Hello",
            system_instruction="Test instruction",
            requested_model="gpt-4o",
            user_primary_key="sk-invalid-test",
            fallback_enabled=True
        ))

        types = [e[0] for e in events]
        assert "fallback_notice" in types
        assert "chunk" in types

        # Check fallback notice event data
        fallback_notice = next(e[1] for e in events if e[0] == "fallback_notice")
        assert fallback_notice["original_model"] == "gpt-4o"
        assert "Switched to backup provider" in fallback_notice["reason"] or "429" in fallback_notice["reason"]

        content = "".join([e[1] for e in events if e[0] == "chunk"])
        assert content == "Fallback answer"
