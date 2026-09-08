import inspect
from unittest.mock import MagicMock, patch
from app.models.ingestion_models import ParentChunk
from app.services.study.generator import _get_llm_candidates
from app.services.rag.promptllm import generate_llm_response, stream_llm_response, stream_resilient_llm_response
from app.services.llm.key_service import OBSOLETE_MODEL_MIGRATIONS


def test_study_generator_prioritizes_user_byok_key():
    mock_supabase = MagicMock()
    user_id = "user_123"

    with patch("app.services.study.generator.get_user_preferences", return_value={"active_model": "gpt-4o"}), \
         patch("app.services.study.generator.get_decrypted_user_key", return_value={"api_key": "sk-user-test-key", "api_base": None}), \
         patch("app.services.study.generator.get_developer_gemini_key", return_value="gemini-dev-key"), \
         patch("app.services.study.generator.get_developer_groq_key", return_value="groq-dev-key"):

        candidates = _get_llm_candidates(mock_supabase, user_id, requested_model="gpt-4o")

        assert len(candidates) >= 2
        # Priority 1 must be the user's custom BYOK key for gpt-4o
        assert candidates[0]["model"] == "gpt-4o"
        assert candidates[0]["api_key"] == "sk-user-test-key"
        assert "User Key" in candidates[0]["label"]

        # Priority 2 is developer Gemini fallback
        assert candidates[1]["model"] == "gemini/gemini-2.5-flash"
        assert candidates[1]["api_key"] == "gemini-dev-key"


def test_study_generator_falls_back_to_dev_keys_when_no_user_key():
    mock_supabase = MagicMock()
    user_id = "user_123"

    with patch("app.services.study.generator.get_user_preferences", return_value={"active_model": "gpt-4o"}), \
         patch("app.services.study.generator.get_decrypted_user_key", return_value=None), \
         patch("app.services.study.generator.get_developer_gemini_key", return_value="gemini-dev-key"), \
         patch("app.services.study.generator.get_developer_groq_key", return_value="groq-dev-key"):

        candidates = _get_llm_candidates(mock_supabase, user_id)

        assert len(candidates) >= 2
        # When no user key exists, developer Gemini is Priority 1
        assert candidates[0]["model"] == "gemini/gemini-2.5-flash"
        assert candidates[0]["api_key"] == "gemini-dev-key"
        # Developer Groq is Priority 2
        assert candidates[1]["model"] == "groq/openai/gpt-oss-120b"


def test_standardized_default_model_identifiers():
    gen_sig = inspect.signature(generate_llm_response)
    assert gen_sig.parameters["model"].default == "groq/openai/gpt-oss-120b"

    stream_sig = inspect.signature(stream_llm_response)
    assert stream_sig.parameters["model"].default == "groq/openai/gpt-oss-120b"

    resilient_sig = inspect.signature(stream_resilient_llm_response)
    assert resilient_sig.parameters["requested_model"].default == "groq/openai/gpt-oss-120b"

    # Verify obsolete model migration maps old groq llama model to gpt-oss-120b
    assert OBSOLETE_MODEL_MIGRATIONS.get("groq/llama-3.3-70b-versatile") == "groq/openai/gpt-oss-120b"


def test_parent_chunk_score_field_and_citation_compatibility():
    # 1. Default score
    chunk1 = ParentChunk(
        id="chunk-1",
        notebook_id="nb-1",
        document_id="doc-1",
        text="Sample text",
        order=0
    )
    assert hasattr(chunk1, "score")
    assert chunk1.score == 1.0

    # 2. Custom score
    chunk2 = ParentChunk(
        id="chunk-2",
        notebook_id="nb-1",
        document_id="doc-1",
        text="High relevance text",
        order=1,
        score=0.945
    )
    assert chunk2.score == 0.945
    assert float(getattr(chunk2, "score", 1.0)) == 0.945
