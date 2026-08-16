from enum import Enum
from typing import List, Union
from app.models.ingestion_models import ParentChunk

class PromptMode(str, Enum):
    STRICT = "strict"      # Strict Source Grounding with pedagogical synthesis
    HYBRID = "hybrid"      # Balanced / Hybrid: Sources first, explicit fallback
    CONCISE = "concise"    # Concise / Executive: Fast takeaways

    # Backwards compatibility aliases
    HONEST = "strict"
    ANSWER_ALL = "hybrid"

def format_context(chunks: List[ParentChunk]) -> str:
    """Formats parent chunks into an indexed, structured context block."""
    if not chunks:
        return "No document context available."
    
    formatted = []
    for idx, chunk in enumerate(chunks):
        formatted.append(f"--- [Source {idx + 1}] (Document ID: {chunk.document_id}) ---\n{chunk.text.strip()}")
    return "\n\n".join(formatted)

def build_augmented_prompt(
    query: str, 
    chunks: List[ParentChunk], 
    mode: Union[PromptMode, str] = PromptMode.HYBRID,
    length_setting: str = "default"
) -> tuple[str, str]:
    """
    Constructs a system instruction and user prompt based on the selected mode.
    Dynamically appends length and behavioral steering constraints.
    """
    context_text = format_context(chunks)

    # 1. Normalize mode string
    if isinstance(mode, str):
        mode_val = mode.lower().strip()
        if mode_val in ("strict", "honest", "exact", "source_only"):
            selected_mode = PromptMode.STRICT
        elif mode_val in ("hybrid", "answer_all", "general", "balanced"):
            selected_mode = PromptMode.HYBRID
        elif mode_val in ("concise", "summary", "bullets", "brief"):
            selected_mode = PromptMode.CONCISE
        else:
            selected_mode = PromptMode.HYBRID
    else:
        selected_mode = mode

    # 2. Length Steering & Anti-Truncation Constraints
    if length_setting == "shorter":
        length_instruction = (
            "RESPONSE BUDGET: Keep the response concise (approx. 150–250 words). "
            "Focus strictly on the core concepts and conclude cleanly with a brief 1-sentence takeaway. "
            "CRITICAL: Always finish all sentences and provide a complete, unbroken response."
        )
    elif length_setting == "longer":
        length_instruction = (
            "RESPONSE BUDGET: Provide an in-depth, comprehensive analysis. "
            "Use structured headings, detailed explanations, and concrete examples. "
            "CRITICAL: Ensure every topic is fully explained and conclude with a well-rounded closing summary without cutting off."
        )
    else:
        length_instruction = (
            "RESPONSE BUDGET: Provide a well-paced, complete explanation (approx. 400–700 words). "
            "Organize clearly with headings and bullet points. "
            "CRITICAL: Ensure all points are fully developed and conclude cleanly. Never leave a thought or sentence unfinished."
        )

    # 3. Base Modes Mapping
    if selected_mode == PromptMode.STRICT:
        system_instruction = f"""You are an expert pedagogical study assistant for a document intelligence workspace.
Your task is to teach the user based STRICTLY on the provided source context. 
Organize answers logically using headings, bullet points, and plain-English explanations.
Synthesize the information naturally to teach the concept—do NOT just copy-paste verbatim chunks.
You are strictly forbidden from introducing outside facts, assumptions, or hallucinations.
If the answer is not present in the context, your entire response must be exactly: 'No source found for this query.'

{length_instruction}"""
        user_prompt = f"Context:\n{context_text}\n\nUser Query: {query}\nAnswer:"

    elif selected_mode == PromptMode.HYBRID:
        system_instruction = f"""You are a helpful AI study assistant. Answer user queries thoroughly.
If the provided source context contains the answer, prioritize it and synthesize it pedagogically.
If the context does not contain the full answer or if no context is found, explicitly state: '⚠️ Not found in your sources. Answering using general knowledge:' and then provide a comprehensive answer from your general knowledge.

{length_instruction}"""
        user_prompt = f"Context:\n{context_text}\n\nUser Query: {query}\nAnswer:"

    elif selected_mode == PromptMode.CONCISE:
        system_instruction = f"""You are an executive summary assistant. Distill the answer into high-impact bullet points based strictly on the provided context. Omit filler and unnecessary preamble.

CRITICAL: Keep the response extremely concise and clear."""
        user_prompt = f"Context:\n{context_text}\n\nUser Query: {query}\nKey Takeaways:"

    else:
        return build_augmented_prompt(query, chunks, mode=PromptMode.HYBRID, length_setting=length_setting)

    return system_instruction, user_prompt