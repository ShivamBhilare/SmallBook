"""
Retrieval-Augmented Generation (RAG) Subsystem

Exports functions for query decomposition, hybrid semantic retrieval,
prompt context augmentation, and resilient multi-provider LLM streaming:
    - `retrieve`, `retrieve_multi`: Hybrid vector search and CrossEncoder reranking.
    - `build_augmented_prompt`, `PromptMode`, `format_context`: Prompt construction and steering.
    - `generate_llm_response`, `stream_llm_response`, `stream_resilient_llm_response`: LiteLLM dispatchers.
"""

from app.services.rag.retriever import retrieve, retrieve_multi
from app.services.rag.augment import build_augmented_prompt, PromptMode, format_context
from app.services.rag.promptllm import (
    generate_llm_response,
    stream_llm_response,
    stream_resilient_llm_response,
)

__all__ = [
    "retrieve",
    "retrieve_multi",
    "build_augmented_prompt",
    "PromptMode",
    "format_context",
    "generate_llm_response",
    "stream_llm_response",
    "stream_resilient_llm_response",
]

