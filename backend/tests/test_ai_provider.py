from backend.app.ai_provider import (
    GEMINI_INTERACTIONS_URL,
    _extract_gemini_text,
    _gemini_schema,
    configured_providers,
    creator_agent_model,
    creator_agent_provider,
    provider_order,
    provider_status,
)


def _clear_provider_env(monkeypatch):
    for key in [
        "AI_PROVIDER",
        "AI_FALLBACK_PROVIDERS",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "LOCAL_AI_BASE_URL",
        "LOCAL_AI_MODEL",
        "LOCAL_AI_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_gemini_is_default_provider(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    assert provider_order() == ["gemini"]
    assert configured_providers() == ["gemini"]
    assert creator_agent_provider() == "gemini"
    assert creator_agent_model() == "gemini-3.8-flash"

    status = provider_status()
    assert status["configured"] is True
    assert status["activeProvider"] == "gemini"
    assert status["activeModel"] == "gemini-3.8-flash"


def test_fallbacks_are_only_used_when_explicit(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("AI_FALLBACK_PROVIDERS", "openrouter,groq")
    monkeypatch.setenv("OPENROUTER_API_KEY", "free-key")

    assert provider_order() == ["gemini", "openrouter", "groq"]
    assert configured_providers() == ["openrouter"]
    assert creator_agent_provider() == "openrouter"
    assert creator_agent_model() == "openrouter/free"


def test_local_provider_requires_base_url_and_model(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_AI_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LOCAL_AI_MODEL", "my-model")

    assert configured_providers() == ["local"]
    assert creator_agent_provider() == "local"
    assert creator_agent_model() == "my-model"


def test_extract_gemini_text_uses_new_steps_shape():
    payload = {
        "id": "int_123",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {"type": "text", "text": '{"summary":"ok"}'},
                ],
            }
        ],
    }

    assert _extract_gemini_text(payload) == '{"summary":"ok"}'


def test_gemini_schema_removes_additional_properties_recursively():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "item": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            }
        },
        "required": ["item"],
    }

    cleaned = _gemini_schema(schema)

    assert "additionalProperties" not in cleaned
    assert "additionalProperties" not in cleaned["properties"]["item"]
    assert cleaned["required"] == ["item"]


def test_gemini_interactions_uses_stable_v1_endpoint():
    assert GEMINI_INTERACTIONS_URL == "https://generativelanguage.googleapis.com/v1/interactions"
