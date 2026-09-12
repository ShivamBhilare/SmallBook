"""Study Artifact LLM Generation Module.

Generates grounded study aids (flashcards and practice quizzes) from ingested
document chunks using LiteLLM with multi-provider fallbacks and resilient JSON
repair pipelines.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import litellm
from litellm import completion
from supabase import Client

from app.models.study_models import (
    FlashcardItemSchema,
    FlashcardSetGenerateSchema,
    QuizGenerateSchema,
    QuizOptionSchema,
    QuizQuestionSchema,
)
from app.services.chat.chat_service import infer_llm_provider
from app.services.llm.free_tier import (
    get_developer_gemini_key,
    get_developer_groq_key,
)
from app.services.llm.key_service import (
    get_decrypted_user_key,
    get_user_preferences,
)

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True


def _clean_json_string(text: str) -> str:
    """Extracts a JSON substring from code fences or surrounding markdown prose.

    Args:
        text: Raw LLM output string.

    Returns:
        Stripped string containing the outermost JSON structure.
    """
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1]

    return text


def _fix_json_syntax(text: str) -> str:
    """Fixes common LLM JSON syntax anomalies such as trailing commas.

    Args:
        text: Pre-trimmed JSON string.

    Returns:
        Cleaned JSON string with trailing commas removed before closing delimiters.
    """
    # Remove trailing commas before closing braces or brackets
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text


def _repair_and_parse_flashcards(raw_text: str, default_title: str) -> FlashcardSetGenerateSchema:
    """Parses flashcards JSON with multi-level syntactic repair and regex recovery.

    Attempts standard parsing first, then applies syntax cleanup (removing trailing
    commas), and finally falls back to regex matching for individual card objects
    if the outer structure is truncated or corrupted.

    Args:
        raw_text: Raw output received from the language model.
        default_title: Fallback title prefix derived from document name.

    Returns:
        Validated FlashcardSetGenerateSchema object.

    Raises:
        ValueError: If flashcards cannot be extracted or parsed through any tier.
    """
    cleaned = _clean_json_string(raw_text)
    try:
        data = json.loads(cleaned)
        return FlashcardSetGenerateSchema(**data)
    except Exception as e:
        logger.warning(f"Standard JSON parse failed ({e}). Trying syntax cleanup...")

    try:
        fixed = _fix_json_syntax(cleaned)
        data = json.loads(fixed)
        return FlashcardSetGenerateSchema(**data)
    except Exception as e:
        logger.warning(f"Syntax cleanup parse failed ({e}). Attempting regex item extraction...")

    # Fallback: Extract individual flashcard objects using regex
    card_pattern = re.compile(
        r'"front_text"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*,\s*"back_text"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
        re.DOTALL
    )
    cards = []
    for match in card_pattern.finditer(raw_text):
        try:
            front = match.group(1).encode().decode('unicode_escape')
            back = match.group(2).encode().decode('unicode_escape')
        except Exception:
            front = match.group(1)
            back = match.group(2)
        cards.append(FlashcardItemSchema(front_text=front, back_text=back))

    if cards:
        logger.info(f"Successfully recovered {len(cards)} flashcards via regex extraction.")
        return FlashcardSetGenerateSchema(title=f"{default_title} - Key Flashcards", cards=cards)

    raise ValueError("Could not parse flashcards from LLM response.")


def _repair_and_parse_quiz(raw_text: str, default_title: str) -> QuizGenerateSchema:
    """Parses practice quiz JSON with multi-level syntactic repair and regex fallback.

    Args:
        raw_text: Raw response string from the language model.
        default_title: Document title to use if title reconstruction is required.

    Returns:
        Validated QuizGenerateSchema containing quiz questions and options.

    Raises:
        ValueError: If questions cannot be parsed or recovered.
    """
    cleaned = _clean_json_string(raw_text)
    try:
        data = json.loads(cleaned)
        return QuizGenerateSchema(**data)
    except Exception as e:
        logger.warning(f"Standard quiz JSON parse failed ({e}). Trying syntax cleanup...")

    # Attempt 2: Syntax cleanup
    try:
        fixed = _fix_json_syntax(cleaned)
        data = json.loads(fixed)
        return QuizGenerateSchema(**data)
    except Exception as e:
        logger.warning(f"Syntax cleanup parse failed ({e}). Attempting regex question recovery...")

    # Attempt 3: Regex recovery of individual questions
    questions = []
    # Match JSON objects that contain "question_text"
    raw_blocks = re.findall(r'\{[^{}]*"question_text"[\s\S]*?"source_chunk_id"[^{}]*\}', raw_text)
    if not raw_blocks:
        raw_blocks = re.findall(r'\{[^{}]*"question_text"[\s\S]*?"explanation"[^{}]*\}', raw_text)

    for block in raw_blocks:
        try:
            q_data = json.loads(_fix_json_syntax(block))
            questions.append(QuizQuestionSchema(**q_data))
        except Exception:
            try:
                q_text_m = re.search(r'"question_text"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', block)
                ans_m = re.search(r'"correct_answer"\s*:\s*"([A-D])"', block)
                exp_m = re.search(r'"explanation"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', block)
                chunk_m = re.search(r'"source_chunk_id"\s*:\s*"([^"]+)"', block)

                # Extract options
                opts = []
                opt_matches = re.findall(r'\{\s*"key"\s*:\s*"([A-D])"\s*,\s*"text"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*\}', block)
                for opt_key, opt_text in opt_matches:
                    opts.append(QuizOptionSchema(key=opt_key, text=opt_text))

                if q_text_m and ans_m and len(opts) >= 2:
                    questions.append(QuizQuestionSchema(
                        question_text=q_text_m.group(1),
                        options=opts,
                        correct_answer=ans_m.group(1),
                        explanation=exp_m.group(1) if exp_m else "",
                        source_chunk_id=chunk_m.group(1) if chunk_m else None
                    ))
            except Exception as extract_err:
                logger.debug(f"Could not extract question block: {extract_err}")

    if questions:
        logger.info(f"Successfully recovered {len(questions)} quiz questions via regex recovery.")
        return QuizGenerateSchema(title=f"{default_title} - Practice Quiz", questions=questions)

    raise ValueError("Could not parse quiz from LLM response.")


def fetch_source_chunks(supabase: Client, source_id: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Fetches document metadata and all associated text chunks in sequential order.

    Args:
        supabase: Supabase client instance.
        source_id: UUID of the source document.

    Returns:
        Tuple containing:
            - source_title: Original filename or title of document.
            - chunks: List of chunk dictionaries containing chunk_index and chunk_text.

    Raises:
        ValueError: If source document record is not found.
    """
    source_res = supabase.table("sources").select("id, original_filename, page_count, ingestion_status").eq("id", source_id).execute()
    if not source_res.data:
        raise ValueError("Selected source document not found.")
    source = source_res.data[0]
    source_title = source.get("original_filename", "Document")

    chunks_res = (
        supabase.table("document_chunks")
        .select("id, chunk_index, chunk_text")
        .eq("source_id", source_id)
        .order("chunk_index", desc=False)
        .execute()
    )
    chunks = chunks_res.data or []

    return source_title, chunks


def _get_llm_candidates(
    supabase: Client,
    user_id: str,
    requested_model: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Constructs a prioritized list of model candidates and keys for generation.

    Prioritizes user BYOK credentials if requested, then developer Gemini 2.5 Flash
    (for 1M token context window support), then developer Groq GPT-OSS 120B.

    Args:
        supabase: Supabase client instance.
        user_id: UUID of the user.
        requested_model: Optional model identifier explicitly requested.

    Returns:
        List of configuration dictionaries with keys 'model', 'api_key',
        'api_base', and 'label'.
    """
    prefs = get_user_preferences(supabase, user_id)
    requested = requested_model or prefs.get("active_model")

    candidates: List[Dict[str, Any]] = []

    # Priority 1: If user configured a specific model with their own BYOK key
    if requested:
        provider = infer_llm_provider(requested) or "groq"
        user_key_data = get_decrypted_user_key(supabase, user_id, provider)
        if user_key_data and user_key_data.get("api_key"):
            candidates.append({
                "model": requested,
                "api_key": user_key_data["api_key"],
                "api_base": user_key_data.get("api_base"),
                "label": f"User Key ({requested})"
            })

    # Priority 2: Free Developer Gemini 2.5 Flash (1M token context window)
    dev_gemini = get_developer_gemini_key()
    if dev_gemini:
        candidates.append({
            "model": "gemini/gemini-2.5-flash",
            "api_key": dev_gemini,
            "api_base": None,
            "label": "Google Gemini 2.5 Flash (Developer Key)"
        })

    # Priority 3: Developer Groq GPT-OSS 120B (with chunk budgeting)
    dev_groq = get_developer_groq_key()
    if dev_groq:
        candidates.append({
            "model": "groq/openai/gpt-oss-120b",
            "api_key": dev_groq,
            "api_base": None,
            "label": "Groq GPT-OSS 120B (Developer Key)"
        })

    # Default fallback candidate if no developer or user keys exist in environment
    if not candidates:
        default_model = requested or "gemini/gemini-2.5-flash"
        candidates.append({
            "model": default_model,
            "api_key": None,
            "api_base": None,
            "label": default_model
        })

    return candidates


def generate_flashcards(
    supabase: Client,
    user_id: str,
    source_id: str,
    custom_prompt: Optional[str] = None,
    num_items: Optional[int] = None,
    requested_model: Optional[str] = None
) -> Tuple[str, FlashcardSetGenerateSchema]:
    """Generates grounded study flashcards from document chunks using LiteLLM.

    Fetches sequential chunks, builds prompt instructions, iterates through
    candidate models, and parses output into a validated flashcard deck.

    Args:
        supabase: Supabase client instance.
        user_id: UUID of the requesting user.
        source_id: UUID of the source document to summarize.
        custom_prompt: Optional user instructions tailoring content focus.
        num_items: Target number of flashcards to generate (defaults to 10).
        requested_model: Optional specific LLM model ID.

    Returns:
        Tuple containing:
            - source_title: Filename of the source document.
            - deck_data: FlashcardSetGenerateSchema containing deck title and cards.

    Raises:
        ValueError: If source document has no content chunks.
        RuntimeError: If all candidate LLM calls fail.
    """
    source_title, all_chunks = fetch_source_chunks(supabase, source_id)
    if not all_chunks:
        raise ValueError(f"No document content found for '{source_title}'. Please ensure document ingestion is completed.")

    # Format full chunks
    full_context_blocks = [
        f"[CHUNK_ID: {c.get('id', '')} | Index: {c.get('chunk_index', idx)}]\n{c.get('chunk_text', '')}"
        for idx, c in enumerate(all_chunks)
    ]
    full_context = "\n\n---\n\n".join(full_context_blocks)

    custom_section = ""
    if custom_prompt and custom_prompt.strip():
        custom_section = f"\nUSER CUSTOM FOCUS / INSTRUCTIONS:\n\"{custom_prompt.strip()}\"\n"

    target_count = num_items if (num_items and num_items > 0) else 10

    system_instruction = f"""You are an expert educator like NotebookLM. 
Your task is to analyze the complete provided document and generate a high-yield set of study flashcards covering all key concepts, definitions, formulas, principles, and critical facts across every section of the document.

CRITICAL RULES:
1. Every card MUST be strictly grounded in the provided text. Never hallucinate outside facts.
2. For each card, specify the supporting chunk UUID in the 'source_chunk_id' field.
3. Keep the 'front_text' concise and test-oriented (e.g. concept, question, term).
4. Keep the 'back_text' clear, thorough, and informative.
5. Generate approximately {target_count} cards to thoroughly cover the document without missing important topics.
6. Return ONLY a valid JSON object matching the requested schema with a deck 'title' and 'cards' array."""

    candidates = _get_llm_candidates(supabase, user_id, requested_model)
    last_error = None

    for cand in candidates:
        model_name = cand["model"]
        api_key = cand["api_key"]
        api_base = cand["api_base"]

        # If Groq candidate, cap context length to prevent 8k TPM rate limit
        context_to_use = full_context
        if "groq" in model_name and len(all_chunks) > 12:
            step = len(all_chunks) / 12
            sampled_chunks = [all_chunks[int(i * step)] for i in range(12)]
            context_to_use = "\n\n---\n\n".join(
                f"[CHUNK_ID: {c.get('id', '')} | Index: {c.get('chunk_index', idx)}]\n{c.get('chunk_text', '')}"
                for idx, c in enumerate(sampled_chunks)
            )

        user_prompt = f"""Generate a comprehensive set of approximately {target_count} study flashcards for the document '{source_title}'.

{custom_section}

DOCUMENT CONTENT:
{context_to_use}

Output format:
{{
  "title": "{source_title} - Key Flashcards",
  "cards": [
    {{
      "front_text": "Question or concept",
      "back_text": "Answer or explanation",
      "source_chunk_id": "chunk-uuid-here"
    }}
  ]
}}
"""

        kwargs = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 8192
        }
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        try:
            resp = completion(**kwargs, response_format={"type": "json_object"})
            content = resp.choices[0].message.content
            return source_title, _repair_and_parse_flashcards(content, source_title)
        except Exception as err:
            logger.warning(f"Flashcard generation failed on candidate {model_name}: {err}")
            try:
                resp = completion(**kwargs)
                content = resp.choices[0].message.content
                return source_title, _repair_and_parse_flashcards(content, source_title)
            except Exception as parse_err:
                last_error = parse_err
                continue

    raise RuntimeError(f"Failed to generate flashcards across LLM providers. Last error: {last_error}")


def generate_quiz(
    supabase: Client,
    user_id: str,
    source_id: str,
    custom_prompt: Optional[str] = None,
    num_items: Optional[int] = None,
    requested_model: Optional[str] = None
) -> Tuple[str, QuizGenerateSchema]:
    """Generates a grounded multiple-choice practice quiz from document chunks.

    Args:
        supabase: Supabase client instance.
        user_id: UUID of the requesting user.
        source_id: UUID of the source document to test.
        custom_prompt: Optional user instructions focusing on specific topics.
        num_items: Target number of questions to generate (defaults to 10).
        requested_model: Optional specific LLM model ID.

    Returns:
        Tuple containing:
            - source_title: Filename of the source document.
            - quiz_data: QuizGenerateSchema containing quiz title and questions.

    Raises:
        ValueError: If source document has no content chunks.
        RuntimeError: If all candidate LLM calls fail.
    """
    source_title, all_chunks = fetch_source_chunks(supabase, source_id)
    if not all_chunks:
        raise ValueError(f"No document content found for '{source_title}'. Please ensure document ingestion is completed.")

    # Format full chunks
    full_context_blocks = [
        f"[CHUNK_ID: {c.get('id', '')} | Index: {c.get('chunk_index', idx)}]\n{c.get('chunk_text', '')}"
        for idx, c in enumerate(all_chunks)
    ]
    full_context = "\n\n---\n\n".join(full_context_blocks)

    custom_section = ""
    if custom_prompt and custom_prompt.strip():
        custom_section = f"\nUSER CUSTOM FOCUS / INSTRUCTIONS:\n\"{custom_prompt.strip()}\"\n"

    target_count = num_items if (num_items and num_items > 0) else 10

    system_instruction = f"""You are an expert examiner like NotebookLM. 
Your task is to analyze the complete provided document and generate a multiple choice practice quiz (MCQs) testing major sections, key concepts, and core facts across the document.

CRITICAL RULES:
1. Every question MUST be strictly grounded in the provided text. Do not invent external facts.
2. Provide 4 distinct options ('A', 'B', 'C', 'D') with exactly one unambiguously correct answer.
3. In 'explanation', clearly explain why the correct answer is right and why distractors are wrong, citing the context.
4. For each question, link the supporting chunk UUID in 'source_chunk_id'.
5. Generate approximately {target_count} questions to thoroughly test understanding across all sections of the document.
6. Return ONLY a valid JSON object matching the requested schema."""

    candidates = _get_llm_candidates(supabase, user_id, requested_model)
    last_error = None

    for cand in candidates:
        model_name = cand["model"]
        api_key = cand["api_key"]
        api_base = cand["api_base"]

        # If Groq candidate, cap context length to prevent 8k TPM rate limit
        context_to_use = full_context
        if "groq" in model_name and len(all_chunks) > 12:
            step = len(all_chunks) / 12
            sampled_chunks = [all_chunks[int(i * step)] for i in range(12)]
            context_to_use = "\n\n---\n\n".join(
                f"[CHUNK_ID: {c.get('id', '')} | Index: {c.get('chunk_index', idx)}]\n{c.get('chunk_text', '')}"
                for idx, c in enumerate(sampled_chunks)
            )

        user_prompt = f"""Generate a comprehensive practice quiz of approximately {target_count} questions for the document '{source_title}'.

{custom_section}

DOCUMENT CONTENT:
{context_to_use}

Output format:
{{
  "title": "{source_title} - Practice Quiz",
  "questions": [
    {{
      "question_text": "Question prompt?",
      "options": [
        {{"key": "A", "text": "First option"}},
        {{"key": "B", "text": "Second option"}},
        {{"key": "C", "text": "Third option"}},
        {{"key": "D", "text": "Fourth option"}}
      ],
      "correct_answer": "A",
      "explanation": "Detailed explanation grounded in the text",
      "source_chunk_id": "chunk-uuid-here"
    }}
  ]
}}
"""

        kwargs = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 8192
        }
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        try:
            resp = completion(**kwargs, response_format={"type": "json_object"})
            content = resp.choices[0].message.content
            return source_title, _repair_and_parse_quiz(content, source_title)
        except Exception as err:
            logger.warning(f"Quiz generation failed on candidate {model_name}: {err}")
            try:
                resp = completion(**kwargs)
                content = resp.choices[0].message.content
                return source_title, _repair_and_parse_quiz(content, source_title)
            except Exception as parse_err:
                last_error = parse_err
                continue

    raise RuntimeError(f"Failed to generate quiz across LLM providers. Last error: {last_error}")
