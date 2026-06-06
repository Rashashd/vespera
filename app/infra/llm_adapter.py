"""LLM provider adapter — selects Anthropic or OpenAI by the available pinned key."""

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class LLMClient:
    """A configured LLM client handle (provider + pinned model + key)."""

    provider: str
    model: str
    api_key: str


def build_llm_client(settings: Settings) -> LLMClient:
    """Return an LLM client for whichever provider key is configured (Anthropic first)."""
    if settings.anthropic_api_key:
        return LLMClient("anthropic", settings.anthropic_model, settings.anthropic_api_key)
    if settings.openai_api_key:
        return LLMClient("openai", settings.openai_model, settings.openai_api_key)
    raise RuntimeError("No LLM API key configured")
