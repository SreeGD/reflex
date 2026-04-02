"""Tests for Phase 2: LLM provider and prompt system."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.chat.mock_chat_llm import MockChatLLM
from backend.app.chat.prompts import (
    compose_prompt,
    get_default_context,
    load_prompt,
)
from backend.app.providers.llm import (
    AnthropicLLMProvider,
    MockLLMProvider,
    OpenAILLMProvider,
    create_llm_provider,
)


# --- LLM Provider tests ---

class TestMockLLMProvider:
    def test_get_chat_model(self):
        provider = MockLLMProvider()
        model = provider.get_model("chat")
        assert isinstance(model, MockChatLLM)

    def test_get_rca_model(self):
        from mock.providers.mock_llm import MockLLM
        provider = MockLLMProvider()
        model = provider.get_model("rca")
        assert isinstance(model, MockLLM)

    def test_get_review_model(self):
        from mock.providers.mock_llm import MockLLM
        provider = MockLLMProvider()
        model = provider.get_model("review")
        assert isinstance(model, MockLLM)


class TestCreateLLMProvider:
    def test_explicit_mock(self):
        provider = create_llm_provider(backend="mock")
        assert isinstance(provider, MockLLMProvider)

    def test_auto_detect_no_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove any API keys that might be set
            env = {k: v for k, v in os.environ.items()
                   if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_BACKEND")}
            with patch.dict(os.environ, env, clear=True):
                provider = create_llm_provider()
                assert isinstance(provider, MockLLMProvider)

    def test_auto_detect_anthropic_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            # Remove other keys that might interfere
            env_patch = {"ANTHROPIC_API_KEY": "test-key"}
            if "LLM_BACKEND" in os.environ:
                env_patch["LLM_BACKEND"] = ""
            with patch.dict(os.environ, env_patch):
                provider = create_llm_provider()
                assert isinstance(provider, AnthropicLLMProvider)

    def test_auto_detect_openai_key(self):
        env = {"OPENAI_API_KEY": "test-key"}
        # Make sure no anthropic key or LLM_BACKEND override
        with patch.dict(os.environ, env, clear=False):
            with patch.dict(os.environ, {"LLM_BACKEND": ""}, clear=False):
                if "ANTHROPIC_API_KEY" not in os.environ:
                    provider = create_llm_provider()
                    assert isinstance(provider, OpenAILLMProvider)

    def test_explicit_backend_overrides_env(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            provider = create_llm_provider(backend="mock")
            assert isinstance(provider, MockLLMProvider)

    def test_env_var_backend(self):
        with patch.dict(os.environ, {"LLM_BACKEND": "mock"}):
            provider = create_llm_provider()
            assert isinstance(provider, MockLLMProvider)

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM backend"):
            create_llm_provider(backend="unsupported")


# --- Prompt system tests ---

class TestLoadPrompt:
    def test_load_base_persona(self):
        content = load_prompt("base_persona.md")
        assert "Reflex" in content
        assert "incident management" in content.lower()

    def test_load_tool_instructions(self):
        content = load_prompt("tool_instructions.md")
        assert "search_knowledge" in content

    def test_load_safety_rails(self):
        content = load_prompt("safety_rails.md")
        assert "blast radius" in content.lower()

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent.md")


class TestComposePrompt:
    def test_composes_all_layers(self):
        prompt = compose_prompt()
        assert "Reflex" in prompt
        assert "search_knowledge" in prompt
        assert "Safety" in prompt

    def test_layers_separated_by_divider(self):
        prompt = compose_prompt()
        assert "---" in prompt

    def test_with_dynamic_context(self):
        prompt = compose_prompt(context={
            "Active incidents": "3",
            "On-call engineer": "Alice",
        })
        assert "Active incidents" in prompt
        assert "Alice" in prompt

    def test_custom_layers(self):
        prompt = compose_prompt(layers=["base_persona.md"])
        assert "Reflex" in prompt
        assert "search_knowledge" not in prompt

    def test_skips_missing_layers(self):
        prompt = compose_prompt(layers=["base_persona.md", "nonexistent.md"])
        assert "Reflex" in prompt


class TestGetDefaultContext:
    def test_returns_time_info(self):
        context = get_default_context()
        assert "Current time (UTC)" in context
        assert "Time of day" in context


# --- Integration: engine still works with LLM provider ---

class TestEngineWithLLMProvider:
    async def test_create_engine_with_mock_provider(self):
        from backend.app.chat.engine import ChatEngine, create_chat_engine

        engine = create_chat_engine()
        assert isinstance(engine, ChatEngine)

    async def test_chat_with_composed_prompt(self):
        from backend.app.chat.engine import create_chat_engine

        engine = create_chat_engine()
        response = await engine.chat("test-p2", "What runbooks exist for pool issues?")
        assert len(response.text) > 0
        assert response.conversation_id == "test-p2"
