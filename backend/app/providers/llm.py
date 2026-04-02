"""LLM provider — configurable model factory for Anthropic, OpenAI, and Mock.

Usage:
    provider = create_llm_provider(backend="anthropic")
    chat_llm = provider.get_model("chat")
    rca_llm = provider.get_model("rca")
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


# Default model configurations per backend
_DEFAULTS = {
    "anthropic": {
        "chat": {"model": "claude-sonnet-4-20250514", "temperature": 0.3},
        "rca": {"model": "claude-sonnet-4-20250514", "temperature": 0},
        "review": {"model": "claude-sonnet-4-20250514", "temperature": 0},
    },
    "openai": {
        "chat": {"model": "gpt-4o", "temperature": 0.3},
        "rca": {"model": "gpt-4o", "temperature": 0},
        "review": {"model": "gpt-4o", "temperature": 0},
    },
}


class MockLLMProvider:
    """Returns mock LLMs — no API keys needed."""

    def get_model(self, purpose: str = "chat") -> Any:
        if purpose == "chat":
            from backend.app.chat.mock_chat_llm import MockChatLLM
            return MockChatLLM()
        else:
            from mock.providers.mock_llm import MockLLM
            return MockLLM()


class AnthropicLLMProvider:
    """Returns ChatAnthropic models configured per purpose."""

    def __init__(self, overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._config = {**_DEFAULTS["anthropic"]}
        if overrides:
            for purpose, settings in overrides.items():
                if purpose in self._config:
                    self._config[purpose] = {**self._config[purpose], **settings}
                else:
                    self._config[purpose] = settings

    def get_model(self, purpose: str = "chat") -> Any:
        from langchain_anthropic import ChatAnthropic

        config = self._config.get(purpose, self._config["chat"])
        return ChatAnthropic(**config)


class OpenAILLMProvider:
    """Returns ChatOpenAI models configured per purpose."""

    def __init__(self, overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._config = {**_DEFAULTS["openai"]}
        if overrides:
            for purpose, settings in overrides.items():
                if purpose in self._config:
                    self._config[purpose] = {**self._config[purpose], **settings}
                else:
                    self._config[purpose] = settings

    def get_model(self, purpose: str = "chat") -> Any:
        from langchain_openai import ChatOpenAI

        config = self._config.get(purpose, self._config["chat"])
        return ChatOpenAI(**config)


def create_llm_provider(
    backend: Optional[str] = None,
    overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Any:
    """Create an LLM provider based on backend name or environment.

    Auto-detection order:
    1. Explicit backend parameter
    2. LLM_BACKEND env var
    3. ANTHROPIC_API_KEY present → anthropic
    4. OPENAI_API_KEY present → openai
    5. Fallback → mock
    """
    if backend is None:
        backend = os.environ.get("LLM_BACKEND", "").lower()

    if not backend:
        if os.environ.get("ANTHROPIC_API_KEY"):
            backend = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            backend = "openai"
        else:
            backend = "mock"

    if backend == "mock":
        return MockLLMProvider()
    elif backend == "anthropic":
        return AnthropicLLMProvider(overrides=overrides)
    elif backend == "openai":
        return OpenAILLMProvider(overrides=overrides)
    else:
        raise ValueError(
            f"Unknown LLM backend: {backend}. "
            f"Supported: mock, anthropic, openai"
        )
