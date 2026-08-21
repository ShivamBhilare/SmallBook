import json
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from supabase import Client

from app.services.authentication.auth_service import login_required, get_supabase_client
from app.services.sources.source_service import get_notebook_sources
from app.services.rag import (
    retrieve_multi,
    build_augmented_prompt,
    stream_resilient_llm_response,
    PromptMode
)
from app.services.llm import (
    get_decrypted_user_key,
    get_user_preferences,
    check_daily_quota,
    increment_daily_quota,
    check_burst_limit,
)
from app.models.chat_models import ChatRequestSchema
from app.services.chat import (
    save_chat_message,
    save_citations,
    get_chat_history,
    clear_chat_history,
    infer_llm_provider
)

router = APIRouter(prefix="/notebooks/{notebook_id}/chat", tags=["Chat"])

@router.get("/history")
def get_notebook_chat_history(
    notebook_id: str,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """
    Retrieves the persistent conversation history for a notebook,
    including linked citations and branch references.
    """
    nb_res = client.table("notebooks").select("id").eq("id", notebook_id).execute()
    if not nb_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found or access denied."
        )

    history = get_chat_history(client, notebook_id)
    return {"messages": history}


@router.delete("/history")
def clear_notebook_chat_history(
    notebook_id: str,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """
    Clears all messages and attached citations for the given notebook.
    """
    nb_res = client.table("notebooks").select("id").eq("id", notebook_id).execute()
    if not nb_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found or access denied."
        )

    success = clear_chat_history(client, notebook_id)
    return {"success": success, "detail": "Chat history cleared successfully."}


@router.post("")
def send_chat_message(
    notebook_id: str,
    payload: ChatRequestSchema,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """
    RAG Streaming Query Endpoint with Full Persistence & Branching:
    1. Validates notebook ownership and active sources.
    2. Persists the incoming User Prompt into `chat_messages` (with `parent_id` for branching).
    3. Runs hybrid retrieval across active source chunks in Qdrant & Supabase.
    4. Reranks and aggregates chunks within the token budget.
    5. Augments the prompt according to the selected mode and length constraints.
    6. Streams LLM response tokens via SSE.
    7. Persists the Assistant response into `chat_messages` and grounded sources into `citations`.
    8. Emits completion metadata (IDs, citations, timings).
    """
    query = (payload.query or "").strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query text cannot be empty."
        )

    # 1. Verify Notebook Access
    nb_res = client.table("notebooks").select("id").eq("id", notebook_id).execute()
    if not nb_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found or access denied."
        )

    # 2. Persist User Prompt to chat_messages
    try:
        user_message_record = save_chat_message(
            client=client,
            notebook_id=notebook_id,
            role="user",
            content=query,
            parent_id=payload.parent_id
        )
        user_msg_id = user_message_record.get("id")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist user chat message: {str(e)}"
        )

    # 3. Resolve Active Source IDs & Filename Mapping
    all_notebook_sources = get_notebook_sources(client, notebook_id)
    source_title_map = {s["id"]: s.get("original_filename", "Source Document") for s in all_notebook_sources}

    if payload.source_ids and len(payload.source_ids) > 0:
        target_source_ids = [sid for sid in payload.source_ids if sid in source_title_map]
    else:
        target_source_ids = list(source_title_map.keys())

    def event_stream():
        try:
            # Emit user message persisted confirmation event
            yield f"data: {json.dumps({'type': 'user_saved', 'user_message_id': user_msg_id, 'parent_id': payload.parent_id})}\n\n"

            # 4. Hybrid Sweet-Spot Retrieval
            t0 = time.perf_counter()
            retrieval_result = None
            if target_source_ids:
                try:
                    retrieval_result = retrieve_multi(
                        query=query,
                        source_ids=target_source_ids,
                        client=client
                    )
                except Exception as e:
                    print(f"Retrieval warning: {e}")

            retrieval_time_ms = (time.perf_counter() - t0) * 1000

            selected_chunks = retrieval_result.get("selected_parents", []) if retrieval_result else []
            used_tokens = retrieval_result.get("used_tokens", 0) if retrieval_result else 0

            # 5. Extract Settings for Prompt Augmentation & Steering
            mode_name = payload.mode or "hybrid"
            length_setting = (payload.response_length or "default").lower()

            system_instruction, user_prompt = build_augmented_prompt(
                query=query,
                chunks=selected_chunks,
                mode=mode_name,
                length_setting=length_setting
            )

            # 6. Resolve User Credentials & LLM Resilience
            user_id = str(user.id if hasattr(user, "id") else user.get("id"))
            user_prefs = get_user_preferences(client, user_id)
            model_name = payload.model or user_prefs.get("active_model") or "groq/llama-3.3-70b-versatile"
            provider_name = infer_llm_provider(model_name)

            # Check if user has personal BYOK key for this provider
            primary_cred = get_decrypted_user_key(client, user_id, provider=provider_name)
            primary_key = primary_cred.get("api_key") if primary_cred else None
            primary_base = primary_cred.get("api_base") if primary_cred else None

            # If user has no personal key, apply Free Tier rate limiting
            if not primary_key:
                if not check_burst_limit(user_id, max_per_minute=4):
                    yield f"data: {json.dumps({'type': 'error', 'error': 'Rate limit: Please wait a moment before sending another message.'})}\n\n"
                    return

                allowed, used, remaining = check_daily_quota(user_id, limit=25, client=client)
                if not allowed:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'Daily Free Tier limit reached (25/25 queries). Add your own free Groq or Gemini API key in Key Settings (top-right) for unlimited access.'})}\n\n"
                    return

                increment_daily_quota(user_id, limit=25, client=client)

            # Resolve other user keys as potential backups
            backup_creds = []
            for p in ["groq", "google", "openai", "anthropic", "openrouter", "custom"]:
                if p != provider_name:
                    b_cred = get_decrypted_user_key(client, user_id, provider=p)
                    if b_cred:
                        backup_creds.append(b_cred)

            # 7. LLM Streaming Generation
            t_llm = time.perf_counter()
            if length_setting == "shorter":
                max_tokens = 1500
            elif length_setting == "longer":
                max_tokens = 8192
            else:
                max_tokens = 4096

            accumulated_tokens = []
            actual_model_used = model_name

            for event_type, event_data in stream_resilient_llm_response(
                prompt=user_prompt,
                system_instruction=system_instruction,
                requested_model=model_name,
                user_primary_key=primary_key,
                user_primary_base=primary_base,
                user_backup_credentials=backup_creds,
                fallback_enabled=user_prefs.get("fallback_enabled", True),
                temperature=0.25,
                max_tokens=max_tokens
            ):
                if event_type == "chunk":
                    accumulated_tokens.append(event_data)
                    yield f"data: {json.dumps({'type': 'chunk', 'content': event_data})}\n\n"
                elif event_type == "fallback_notice":
                    actual_model_used = event_data.get("fallback_model", actual_model_used)
                    yield f"data: {json.dumps({'type': 'fallback_notice', **event_data})}\n\n"
                elif event_type == "used_model":
                    actual_model_used = event_data
                elif event_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'error': event_data})}\n\n"

            llm_time_ms = (time.perf_counter() - t_llm) * 1000
            full_assistant_content = "".join(accumulated_tokens).strip()

            # 8. Format Citation Objects
            citations_for_db = []
            citations_for_ui = []
            for chunk in selected_chunks:
                doc_title = source_title_map.get(chunk.document_id, "Document")
                snippet = (chunk.text[:160] + "...") if len(chunk.text) > 160 else chunk.text
                citations_for_db.append({
                    "chunk_id": getattr(chunk, "id", None),
                    "source_title": doc_title,
                    "page_number": (getattr(chunk, "order", 0) or 0) + 1,
                    "chunk_snapshot": chunk.text[:500] if hasattr(chunk, "text") else "",
                    "relevance_score": getattr(chunk, "score", 1.0)
                })
                citations_for_ui.append({
                    "id": getattr(chunk, "id", None),
                    "document_id": chunk.document_id,
                    "document_title": doc_title,
                    "order": getattr(chunk, "order", 0),
                    "text_snippet": snippet
                })

            # 9. Persist Assistant Message to chat_messages
            actual_provider_name = infer_llm_provider(actual_model_used)
            assistant_msg_record = save_chat_message(
                client=client,
                notebook_id=notebook_id,
                role="assistant",
                content=full_assistant_content,
                parent_id=user_msg_id,
                llm_provider=actual_provider_name,
                llm_model=actual_model_used
            )
            assistant_msg_id = assistant_msg_record.get("id")

            # 10. Persist Citations to citations table
            if assistant_msg_id and citations_for_db:
                try:
                    save_citations(assistant_msg_id, citations_for_db)
                except Exception as cit_save_err:
                    print(f"Failed to persist citations: {cit_save_err}")

            timings = {
                "retrieval_ms": round(retrieval_time_ms, 2),
                "llm_ms": round(llm_time_ms, 2),
                "total_ms": round(retrieval_time_ms + llm_time_ms, 2),
            }
            if retrieval_result and "timings_ms" in retrieval_result:
                timings["retrieval_breakdown"] = retrieval_result["timings_ms"]

            metadata_payload = {
                "type": "metadata",
                "message_id": assistant_msg_id,
                "user_message_id": user_msg_id,
                "parent_id": user_msg_id,
                "query": query,
                "mode": mode_name,
                "sources": citations_for_ui,
                "used_tokens": used_tokens,
                "timings_ms": timings
            }
            yield f"data: {json.dumps(metadata_payload)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as err:
            yield f"data: {json.dumps({'type': 'error', 'error': str(err)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )