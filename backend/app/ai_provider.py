from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "groq": "openai/gpt-oss-20b",
    "openrouter": "openrouter/free",
    "openai": "gpt-5.6-luna",
    "local": "",
}

PROVIDER_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
}

PROVIDER_MODEL_VARS = {
    "gemini": "GEMINI_MODEL",
    "groq": "GROQ_MODEL",
    "openrouter": "OPENROUTER_MODEL",
    "openai": "OPENAI_MODEL",
    "local": "LOCAL_AI_MODEL",
}

SUPPORTED_PROVIDERS = ("gemini", "groq", "openrouter", "openai", "local")


class AIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    model: str


def _clean_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    return provider if provider in SUPPORTED_PROVIDERS else ""


def provider_model(provider: str) -> str:
    provider = _clean_provider(provider)
    if not provider:
        return ""
    env_name = PROVIDER_MODEL_VARS[provider]
    return os.getenv(env_name, DEFAULT_MODELS[provider]).strip() or DEFAULT_MODELS[provider]


def provider_configured(provider: str) -> bool:
    provider = _clean_provider(provider)
    if not provider:
        return False
    if provider == "local":
        return bool(
            os.getenv("LOCAL_AI_BASE_URL", "").strip()
            and provider_model("local")
        )
    key_name = PROVIDER_KEYS[provider]
    return bool(os.getenv(key_name, "").strip())


def provider_order() -> list[str]:
    primary = _clean_provider(os.getenv("AI_PROVIDER", "gemini")) or "gemini"
    fallbacks = [
        _clean_provider(item)
        for item in os.getenv("AI_FALLBACK_PROVIDERS", "").split(",")
    ]
    result: list[str] = []
    for provider in [primary, *fallbacks]:
        if provider and provider not in result:
            result.append(provider)
    return result


def configured_providers() -> list[str]:
    return [provider for provider in provider_order() if provider_configured(provider)]


def creator_agent_configured() -> bool:
    return bool(configured_providers())


def creator_agent_provider() -> str:
    configured = configured_providers()
    if configured:
        return configured[0]
    order = provider_order()
    return order[0] if order else "gemini"


def creator_agent_model() -> str:
    return provider_model(creator_agent_provider())


def provider_status() -> dict[str, Any]:
    active = creator_agent_provider()
    return {
        "configured": creator_agent_configured(),
        "activeProvider": active,
        "activeModel": provider_model(active),
        "providerOrder": provider_order(),
        "configuredProviders": configured_providers(),
    }


def _json_result(raw: str, provider: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIProviderError(
            f"{provider} returned invalid JSON for a structured response."
        ) from exc
    if not isinstance(value, dict):
        raise AIProviderError(f"{provider} returned a non-object structured response.")
    return value


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    for step in reversed(payload.get("steps", []) or []):
        if step.get("type") != "model_output":
            continue
        text_parts = [
            str(part.get("text"))
            for part in step.get("content", []) or []
            if part.get("type") == "text" and part.get("text")
        ]
        if text_parts:
            return "".join(text_parts)

    for output in reversed(payload.get("outputs", []) or []):
        if output.get("type") == "text" and output.get("text"):
            return str(output["text"])

    if payload.get("output_text"):
        return str(payload["output_text"])

    raise AIProviderError("Gemini returned no usable text output.")


def _extract_openai_response_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                return str(part["text"])
    if payload.get("output_text"):
        return str(payload["output_text"])
    raise AIProviderError("OpenAI returned no usable text output.")


def _extract_chat_text(payload: dict[str, Any], provider: str) -> str:
    choices = payload.get("choices", []) or []
    if not choices:
        raise AIProviderError(f"{provider} returned no choices.")
    message = choices[0].get("message", {}) or {}
    content = message.get("content")
    if isinstance(content, str) and content:
        return content
    if isinstance(content, list):
        chunks = [
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and item.get("text")
        ]
        if chunks:
            return "".join(chunks)
    raise AIProviderError(f"{provider} returned no usable text output.")


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove OpenAI-only strictness fields while preserving JSON Schema shape."""
    if isinstance(schema, list):
        return [_gemini_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if isinstance(value, dict):
            cleaned[key] = _gemini_schema(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _gemini_schema(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned


async def _request_json(
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise AIProviderError(f"{provider} could not be reached: {exc}") from exc

    if response.is_error:
        detail = f"{provider} request failed (HTTP {response.status_code})."
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or detail)
                elif payload.get("message"):
                    detail = str(payload.get("message"))
        except ValueError:
            pass
        raise AIProviderError(detail)

    try:
        return response.json()
    except ValueError as exc:
        raise AIProviderError(f"{provider} returned a non-JSON API response.") from exc


async def _gemini_structured(
    *,
    instructions: str,
    prompt: str,
    schema: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise AIProviderError("GEMINI_API_KEY is not configured.")

    model = provider_model("gemini")
    body = {
        "model": model,
        "system_instruction": instructions,
        "input": prompt,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": _gemini_schema(schema),
        },
        "generation_config": {
            "max_output_tokens": max_output_tokens,
        },
    }
    payload = await _request_json(
        url=GEMINI_INTERACTIONS_URL,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        body=body,
        provider="Gemini",
    )
    return _json_result(_extract_gemini_text(payload), "Gemini")


async def _chat_structured(
    *,
    provider: str,
    url: str,
    api_key: str,
    model: str,
    instructions: str,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int,
    extra_headers: dict[str, str] | None = None,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
        "max_completion_tokens": max_output_tokens,
    }
    if extra_body:
        body.update(extra_body)

    payload = await _request_json(
        url=url,
        headers=headers,
        body=body,
        provider=provider,
    )
    return _json_result(_extract_chat_text(payload, provider), provider)


async def _groq_structured(
    *,
    instructions: str,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise AIProviderError("GROQ_API_KEY is not configured.")
    return await _chat_structured(
        provider="Groq",
        url=GROQ_CHAT_URL,
        api_key=api_key,
        model=provider_model("groq"),
        instructions=instructions,
        prompt=prompt,
        schema_name=schema_name,
        schema=schema,
        max_output_tokens=max_output_tokens,
    )


async def _openrouter_structured(
    *,
    instructions: str,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise AIProviderError("OPENROUTER_API_KEY is not configured.")
    return await _chat_structured(
        provider="OpenRouter",
        url=OPENROUTER_CHAT_URL,
        api_key=api_key,
        model=provider_model("openrouter"),
        instructions=instructions,
        prompt=prompt,
        schema_name=schema_name,
        schema=schema,
        max_output_tokens=max_output_tokens,
        extra_headers={
            "HTTP-Referer": os.getenv(
                "OPENROUTER_SITE_URL",
                "https://github.com/KristineLio/christina-lab",
            ),
            "X-Title": "Christina Lab",
        },
        extra_body={
            "provider": {"require_parameters": True},
        },
    )


async def _openai_structured(
    *,
    instructions: str,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIProviderError("OPENAI_API_KEY is not configured.")

    body = {
        "model": provider_model("openai"),
        "instructions": instructions,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }
    payload = await _request_json(
        url=OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        body=body,
        provider="OpenAI",
    )
    return _json_result(_extract_openai_response_text(payload), "OpenAI")


async def _local_structured(
    *,
    instructions: str,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    base_url = os.getenv("LOCAL_AI_BASE_URL", "").strip().rstrip("/")
    model = provider_model("local")
    if not base_url or not model:
        raise AIProviderError(
            "LOCAL_AI_BASE_URL and LOCAL_AI_MODEL must both be configured."
        )
    api_key = os.getenv("LOCAL_AI_API_KEY", "").strip() or "local"
    return await _chat_structured(
        provider="Local AI",
        url=base_url + "/v1/chat/completions",
        api_key=api_key,
        model=model,
        instructions=instructions,
        prompt=prompt,
        schema_name=schema_name,
        schema=schema,
        max_output_tokens=max_output_tokens,
    )


async def generate_structured(
    *,
    instructions: str,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int = 6000,
) -> tuple[dict[str, Any], ProviderAttempt]:
    attempts: list[str] = []
    configured = configured_providers()

    if not configured:
        wanted = ", ".join(provider_order())
        raise AIProviderError(
            "Creator Agent has no configured AI provider. "
            f"Configured order: {wanted}. Add the matching server-side API key."
        )

    for provider in configured:
        model = provider_model(provider)
        try:
            kwargs = {
                "instructions": instructions,
                "prompt": prompt,
                "schema_name": schema_name,
                "schema": schema,
                "max_output_tokens": max_output_tokens,
            }
            if provider == "gemini":
                result = await _gemini_structured(
                    instructions=instructions,
                    prompt=prompt,
                    schema=schema,
                    max_output_tokens=max_output_tokens,
                )
            elif provider == "groq":
                result = await _groq_structured(**kwargs)
            elif provider == "openrouter":
                result = await _openrouter_structured(**kwargs)
            elif provider == "openai":
                result = await _openai_structured(**kwargs)
            elif provider == "local":
                result = await _local_structured(**kwargs)
            else:
                continue
            return result, ProviderAttempt(provider=provider, model=model)
        except AIProviderError as exc:
            attempts.append(f"{provider}: {exc}")

    raise AIProviderError(
        "All configured Creator Agent providers failed. " + " | ".join(attempts)
    )
