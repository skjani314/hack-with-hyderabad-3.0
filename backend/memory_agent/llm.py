"""Groq LLM calls that return validated Pydantic models (Groq strict structured outputs).

Every data-producing LLM call goes through `structured()`: the output type is sent as a JSON schema with
`strict: true`, so Groq's constrained decoding guarantees the shape and Pydantic validates it again on our side.
Structured outputs and tool use cannot be combined on Groq, so callers fetch memory first and pass it in the prompt.

Groq free tier: 8,000 tokens per minute per model (x-ratelimit-limit-tokens). Groq's rate-limit docs don't say
exactly how the requested `max_tokens` or gpt-oss's hidden reasoning count against that budget, so we keep
`max_tokens` tight and effort low where accuracy allows (briefs use medium: low misread "instead of"), and when
Groq returns 429 with `retry-after` (documented, in seconds) we wait and retry on the server instead of showing the
salesperson an error.
"""
import asyncio
import os
import re
from typing import TypeVar

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider

from .errors import ConfigMissing, LLMFailed, LLMRateLimited, LLMRequestTooLarge

T = TypeVar("T", bound=BaseModel)

# All three support Groq strict mode. If one is rate limited or errors, the next one answers.
MODELS = [os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
MAX_INPUT_TOKENS = 4500
MAX_WAIT_SECONDS = 25   # longest server-side wait for Groq's per-minute window before giving up


def approx_tokens(text: str) -> int:
    return len(text) // 4 + 1


def keys() -> list[str]:
    """Groq keys in rotation order: GROQ_API_KEYS (comma-separated), else GROQ_API_KEY. Each key has its own
    per-minute and per-day budget (the free tier allows 200,000 tokens per day per model)."""
    ks = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
    ks = ks or [k for k in [os.getenv("GROQ_API_KEY", "").strip()] if k]
    if not ks:
        raise ConfigMissing("GROQ_API_KEY (or GROQ_API_KEYS) is not set")
    return list(dict.fromkeys(ks))


def _model(effort_gpt_oss: str = "low"):
    """Every model on every key, best model first: gpt-oss-120b on key 1, key 2, key 3, then the smaller models.
    A key that has hit its limit fails fast and the next one answers."""
    providers = [GroqProvider(api_key=k) for k in keys()]
    models = []
    for name in MODELS:
        for provider in providers:
            # pydantic-ai's qwen profile disables native JSON schema output, but Groq supports strict mode for this
            # model (console.groq.com/docs/structured-outputs), so we switch it on.
            profile = {**dict(provider.model_profile(name) or {}), "supports_json_schema_output": True}
            # gpt-oss accepts graded effort (low/medium/high); qwen3 only none/default.
            effort = effort_gpt_oss if name.startswith("openai/gpt-oss") else "none"
            models.append(GroqModel(name, provider=provider, profile=profile,
                                    settings={"temperature": 0.2, "groq_reasoning_effort": effort}))
    return FallbackModel(*models)


def _flatten(e: BaseException) -> list[BaseException]:
    subs = getattr(e, "exceptions", None)
    return [x for s in subs for x in _flatten(s)] if subs else [e]


def _retry_after(errors: list[BaseException]) -> float | None:
    """Seconds Groq asked us to wait (Retry-After header, or 'try again in 7.2s' in the message). None = unknown."""
    waits = []
    for e in errors:
        headers = getattr(e, "headers", None) or {}
        if headers.get("retry-after"):
            try:
                waits.append(float(headers["retry-after"]))
                continue
            except ValueError:
                pass
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", str(getattr(e, "body", "")) + str(e))
        if m:
            secs = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1) + 60 * int(m.group(1) or 0)
            waits.append(secs)
    return min(waits) if waits else None  # the first model to free up is enough


def _status(e: BaseException) -> int | None:
    return e.status_code if isinstance(e, ModelHTTPError) else None


def _too_large(errors: list[BaseException]) -> tuple[int, int] | None:
    """(limit, requested) from Groq's 413 text 'Limit 8000, Requested 8421'. The smallest overshoot wins, since
    any model in the fallback chain that fits is enough. Measured: "Requested" is the PROMPT (a 6,529-token prompt
    with max_tokens=3000 was accepted under an 8,000 limit), so the fix for a 413 is a shorter prompt."""
    found = []
    for e in errors:
        m = re.search(r"Limit (\d+), Requested (\d+)", str(getattr(e, "body", "")) + str(e))
        if m:
            found.append((int(m.group(1)), int(m.group(2))))
    return min(found, key=lambda lr: lr[1] - lr[0]) if found else None


async def structured(output_type: type[T], instructions: str, prompt: str, max_tokens: int = 2000,
                     effort: str = "low") -> T:
    """One strict structured LLM call. Waits out Groq's per-minute limit once. Raises LLMRateLimited,
    LLMRequestTooLarge (carrying Groq's limit and requested size, so the caller can shorten the prompt) or LLMFailed,
    never a raw provider error."""
    agent = Agent(_model(effort), output_type=NativeOutput(output_type, strict=True), instructions=instructions,
                  retries=1)
    waited = False
    for _ in range(2):
        try:
            return (await agent.run(prompt, model_settings={"max_tokens": max_tokens})).output
        except ConfigMissing:
            raise
        except Exception as e:  # provider errors arrive wrapped in exception groups by FallbackModel
            errors = _flatten(e)
            text = " | ".join(str(x) for x in errors)
            statuses = {_status(x) for x in errors}
            if 413 in statuses or "Request too large" in text:
                sizes = _too_large(errors)
                detail = f" (limit {sizes[0]:,}, this request {sizes[1]:,} tokens)" if sizes else ""
                err = LLMRequestTooLarge(f"This request is too large for the Groq key's per-minute limit{detail}. "
                                         "Try a shorter question or fewer focus chips.")
                err.limit, err.requested = sizes if sizes else (None, None)
                raise err from e
            if 429 in statuses or "rate_limit" in text or "over capacity" in text:
                wait = _retry_after(errors)
                if not waited and (wait is None or wait <= MAX_WAIT_SECONDS):
                    waited = True
                    await asyncio.sleep((wait if wait is not None else 10) + 0.5)
                    continue
                secs = f" in about {int(wait) + 1} seconds" if wait else " in a minute"
                raise LLMRateLimited(f"Groq is busy (free-tier limit of 8,000 tokens per minute). Try again{secs}.") from e
            raise LLMFailed(f"LLM error: {text[:300]}") from e
    raise LLMFailed("LLM error: no answer after retrying")
