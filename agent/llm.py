"""Groq chat client with rate-limit backoff."""
import os
import time

from dotenv import load_dotenv

from agent.schema import ROOT

# Most capable model on this Groq account (checked 2026-10-15: gpt-oss-120b/20b, qwen3.8-27b, allam-2-7b)
DEFAULT_MODEL = "openai/gpt-oss-120b"
REASONING_EFFORT = "medium"  # gpt-oss models only
_client = None


def model_name() -> str:
    load_dotenv(ROOT / ".env")
    return os.environ.get("GROQ_MODEL") or DEFAULT_MODEL


def chat(messages: list[dict], max_tokens: int = 4096, retries: int = 8) -> str:
    """One chat completion at temperature 0; waits and retries on rate limits."""
    global _client
    import groq

    if _client is None:
        load_dotenv(ROOT / ".env")
        _client = groq.Groq(api_key=os.environ["GROQ_API_KEY"])
    delay = 5.0
    for attempt in range(retries):
        try:
            extra = {"reasoning_effort": REASONING_EFFORT} if "gpt-oss" in model_name() else {}
            r = _client.chat.completions.create(
                model=model_name(), messages=messages, temperature=0, max_tokens=max_tokens, **extra)
            return r.choices[0].message.content or ""
        except groq.RateLimitError as e:
            if attempt == retries - 1:
                raise
            retry_after = e.response.headers.get("retry-after") if e.response is not None else None
            wait = float(retry_after) if retry_after else delay
            print(f"  rate limited; waiting {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 2, 120)
        except (groq.APIConnectionError, groq.InternalServerError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 120)
    raise RuntimeError("unreachable")
