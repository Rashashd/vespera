"""Provider-pinned LangChain chat model with tool-binding for the drafting agent."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from app.core.config import Settings
from app.infra.llm_adapter import build_llm_client


def build_agent_chat_model(settings: Settings) -> BaseChatModel:
    """Return the LangChain chat model for the configured provider (Anthropic-first).

    Raises RuntimeError if no API key is configured (mirroring build_llm_client).
    """
    llm = build_llm_client(settings)
    if llm.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=llm.model,
            api_key=llm.api_key,  # type: ignore[arg-type]
            max_tokens=settings.agent_llm_max_tokens,
        )
    else:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=llm.model,
            api_key=llm.api_key,  # type: ignore[arg-type]
            max_tokens=settings.agent_llm_max_tokens,
        )
