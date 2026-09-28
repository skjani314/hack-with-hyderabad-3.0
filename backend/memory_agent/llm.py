"""Groq LLM calls that return validated Pydantic models (Groq strict structured outputs).

Every data-producing LLM call goes through `structured()`: the output type is sent as a JSON schema with
`strict: true`, so Groq's constrained decoding guarantees the shape and Pydantic validates it again on our side.
Structured outputs and tool use cannot be combined on Groq, so callers fetch memory first and pass it in the prompt.
"""
import os
from typing import TypeVar

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider

from .errors import ConfigMissing, LLMFailed, LLMRateLimited

T = TypeVar("T", bound=BaseModel)

# All three support Groq strict mode. If one is rate limited or errors, the next one answers.
MODELS = [os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]

# Groq free tier: 8,000 tokens per minute per model (x-ratelimit-limit-tokens), and the whole request
# (prompt + schema + output + hidden reasoning) counts. Callers keep prompts under this many input tokens.
MAX_INPUT_TOKENS = 4500


def approx_tokens(text: str) -> int:
    return len(text) // 4 + 1


def _key() -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise ConfigMissing("GROQ_API_KEY is not set")
    return key


def _model():
    provider = GroqProvider(api_key=_key())
    models = []
    for name in MODELS:
        # pydantic-ai's qwen profile disables native JSON schema output, but Groq supports strict mode for this
        # model (console.groq.com/docs/structured-outputs), so we switch it on.
        profile = {**dict(provider.model_profile(name) or {}), "supports_json_schema_output": True}
        models.append(GroqModel(name, provider=provider, profile=profile, settings={"temperature": 0.2}))
    return FallbackModel(*models)


def _flatten(e: BaseException) -> list[BaseException]:
    subs = getattr(e, "exceptions", None)
    return [x for s in subs for x in _flatten(s)] if subs else [e]


async def structured(output_type: type[T], instructions: str, prompt: str, max_tokens: int = 3000) -> T:
    """One strict structured LLM call. Raises LLMRateLimited or LLMFailed, never a raw provider error."""
    agent = Agent(_model(), output_type=NativeOutput(output_type, strict=True), instructions=instructions,
                  retries=1)
    try:
        result = await agent.run(prompt, model_settings={"max_tokens": max_tokens})
    except ConfigMissing:
        raise
    except Exception as e:  # provider errors arrive wrapped in exception groups by FallbackModel
        text = " | ".join(str(x) for x in _flatten(e))
        if any(s in text for s in ("rate_limit", "429", "413", "over capacity", "Request too large")):
            raise LLMRateLimited("The LLM (Groq) is at its rate limit. Wait a minute and try again.") from e
        raise LLMFailed(f"LLM error: {text[:300]}") from e
    return result.output
