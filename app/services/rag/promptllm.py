import os
from typing import Optional, Generator
import litellm
from litellm import completion

# Suppress verbose debug logs in production
litellm.suppress_debug_info = True

def generate_llm_response(
    prompt: str,
    system_instruction: str = "You are a helpful, strictly constrained AI assistant.",
    model: str = "gemini/gemini-2.5-flash",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """
    Sends prompts to any supported LLM provider using LiteLLM.
    
    Model format examples:
      - Google Gemini: 'gemini/gemini-2.5-flash'
      - OpenAI: 'gpt-4o' or 'gpt-4o-mini'
      - Anthropic: 'claude-3-5-sonnet-20241022'
      - Groq: 'groq/llama-3.3-70b-versatile'
      - Local Ollama: 'ollama/llama3'
    """
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt}
    ]

    try:
        response = completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error executing LLM request ({model}): {str(e)}"

def stream_llm_response(
    prompt: str,
    system_instruction: str = "You are a helpful, strictly constrained AI assistant.",
    model: str = "gemini/gemini-2.5-flash",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """Streams response chunks for real-time frontend chat interfaces."""
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt}
    ]

    try:
        response = completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True
        )
        for chunk in response:
            if hasattr(chunk, "choices") and chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    yield delta.content
    except Exception as e:
        yield f"\n\n[Stream Error ({model}): {str(e)}]"