import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from foodbridge.integrations.extraction import extract
from foodbridge.settings import Settings

NOW = datetime(2026, 10, 30, 20, tzinfo=UTC)
TEXT = "Food: rice. 10 kg. Allergens: none."
PROVIDERS = ["openai", "gemini", "anthropic", "openai_compatible"]


@pytest.fixture(autouse=True)
def clean_provider_environment(monkeypatch):
    import os

    for name in os.environ:
        if name.startswith("FOODBRIDGE_EXTRACTION_") or name in {
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "ANTHROPIC_API_KEY",
            "FOODBRIDGE_OPENAI_API_KEY",
            "FOODBRIDGE_GEMINI_API_KEY",
            "FOODBRIDGE_ANTHROPIC_API_KEY",
        }:
            monkeypatch.delenv(name)


def configured(provider, **kwargs):
    return Settings(
        _env_file=None,
        extraction_provider=provider,
        extraction_model="test-model",
        extraction_api_key="private-test-key",
        extraction_base_url="https://example.test/v1" if provider == "openai_compatible" else None,
        **kwargs,
    )


def response_body(provider, text):
    return {
        "openai": {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        },
        "gemini": {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [{"text": "internal reasoning", "thought": True}, {"text": text}]
                    },
                }
            ]
        },
        "anthropic": {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]},
        "openai_compatible": {"choices": [{"finish_reason": "stop", "message": {"content": text}}]},
    }[provider]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("bad_quote", [False, True])
def test_protocol_and_shared_source_validation(provider, bad_quote):
    proposal = {
        "fields": {"quantity_kg": 10},
        "evidence": [{"field": "quantity_kg", "quote": "invented" if bad_quote else "10 kg"}],
    }

    def handler(request):
        body = json.loads(request.content)
        assert "private-test-key" not in str(request.url)
        assert "private-test-key" not in request.content.decode()
        assert body["model"] == "test-model" if provider != "gemini" else True
        if provider == "openai":
            assert request.url.host == "api.openai.com"
            assert body["store"] is False
            assert body["text"]["format"]["strict"] is True
        elif provider == "gemini":
            assert request.url.host == "generativelanguage.googleapis.com"
            assert request.url.path.endswith("/test-model:generateContent")
            assert request.headers["x-goog-api-key"] == "private-test-key"
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            assert "responseJsonSchema" in body["generationConfig"]
        elif provider == "anthropic":
            assert request.url.host == "api.anthropic.com"
            assert request.headers["x-api-key"] == "private-test-key"
            assert request.headers["anthropic-version"] == "2023-06-01"
            schema = body["output_config"]["format"]["schema"]
            assert (
                "exclusiveMinimum"
                not in schema["$defs"]["ProposedFields"]["properties"]["quantity_kg"]["anyOf"][0]
            )
        else:
            assert request.url == "https://example.test/v1/chat/completions"
            assert body["response_format"]["json_schema"]["strict"] is True
        if provider in {"openai", "openai_compatible"}:
            assert request.headers["authorization"] == "Bearer private-test-key"
        assert request.extensions["timeout"]["read"] == 8
        return httpx.Response(200, json=response_body(provider, json.dumps(proposal)))

    result = extract(TEXT, "UTC", NOW, configured(provider), httpx.MockTransport(handler))
    assert result.provider == provider
    assert result.fields.quantity_kg == (None if bad_quote else 10)
    assert "private-test-key" not in result.model_dump_json()


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("failure", ["http", "timeout", "malformed", "invalid", "incomplete"])
def test_all_provider_failures_fall_back_visibly(provider, failure):
    def handler(request):
        if failure == "http":
            return httpx.Response(401, json={"error": "private-test-key"})
        if failure == "timeout":
            raise httpx.ReadTimeout("private-test-key", request=request)
        text = (
            "bad json"
            if failure == "malformed"
            else json.dumps({"fields": {"quantity_kg": -10}, "evidence": []})
        )
        body = response_body(provider, text)
        if failure == "incomplete":
            body = {
                "openai": {"status": "incomplete"},
                "gemini": {"candidates": [{"finishReason": "SAFETY"}]},
                "anthropic": {"stop_reason": "refusal"},
                "openai_compatible": {"choices": [{"finish_reason": "length"}]},
            }[provider]
        return httpx.Response(200, json=body)

    result = extract(TEXT, "UTC", NOW, configured(provider), httpx.MockTransport(handler))
    assert result.provider == "rules"
    assert result.fields.quantity_kg == 10
    assert any(issue.code == "provider_unavailable" for issue in result.issues)
    assert "private-test-key" not in result.model_dump_json()


@pytest.mark.parametrize(
    "variable,provider",
    [
        ("OPENAI_API_KEY", "openai"),
        ("GEMINI_API_KEY", "gemini"),
        ("GOOGLE_API_KEY", "gemini"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("FOODBRIDGE_GEMINI_API_KEY", "gemini"),
    ],
)
def test_key_only_selection_from_env_and_dotenv(variable, provider, monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text(f"{variable}=private-test-key\n")
    for settings in (Settings(_env_file=path),):
        assert settings.extraction_provider == provider
        assert settings.extraction_model
        assert settings.extraction_api_key.get_secret_value() == "private-test-key"
    monkeypatch.setenv(variable, "private-test-key")
    assert Settings(_env_file=None).extraction_provider == provider


def test_no_key_rules_opt_out_and_ambiguous_keys(monkeypatch):
    assert Settings(_env_file=None).extraction_provider == "rules"
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    with pytest.raises(ValidationError, match="ambiguous"):
        Settings(_env_file=None)
    assert Settings(_env_file=None, extraction_provider="rules").extraction_provider == "rules"
    chosen = Settings(_env_file=None, extraction_provider="gemini")
    assert chosen.extraction_api_key.get_secret_value() == "gemini-test-key"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extraction_provider": "gemini"},
        {"extraction_api_key": "private-test-key"},
        {"extraction_provider": "openai_compatible", "extraction_api_key": "private-test-key"},
        {
            "extraction_provider": "openai_compatible",
            "extraction_api_key": "private-test-key",
            "extraction_model": "model",
            "extraction_base_url": "http://example.test/v1",
        },
        {"extraction_provider": "openai", "extraction_api_key": " "},
    ],
)
def test_invalid_configuration_fails_without_exposing_secrets(kwargs):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **kwargs)
    assert "private-test-key" not in str(caught.value)


def test_compatible_json_mode_still_validates_locally():
    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert "quantity_kg" in body["messages"][0]["content"]
        return httpx.Response(
            200, json=response_body("openai_compatible", '{"fields": {}, "evidence": []}')
        )

    result = extract(
        TEXT,
        "UTC",
        NOW,
        configured("openai_compatible", extraction_response_format="json_object"),
        httpx.MockTransport(handler),
    )
    assert result.provider == "openai_compatible"
    assert result.fields.quantity_kg is None


@pytest.mark.parametrize(
    "provider,body",
    [
        (
            "openai",
            {
                "status": "completed",
                "output": [
                    {"type": "message", "content": [{"type": "refusal", "refusal": "refused"}]}
                ],
            },
        ),
        ("gemini", {"promptFeedback": {"blockReason": "SAFETY"}}),
        ("anthropic", {"stop_reason": "refusal"}),
        (
            "openai_compatible",
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "{}", "refusal": "refused"}}
                ]
            },
        ),
    ],
)
def test_refusals_and_blocked_prompts_are_not_proposals(provider, body):
    result = extract(
        TEXT,
        "UTC",
        NOW,
        configured(provider),
        httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
    )
    assert result.provider == "rules"
    assert any(issue.code == "provider_unavailable" for issue in result.issues)


def test_explicit_provider_never_uses_another_vendors_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-only")
    with pytest.raises(ValidationError, match="requires a server API key"):
        Settings(_env_file=None, extraction_provider="gemini")


def test_generic_key_and_model_override_vendor_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "vendor-key")
    settings = Settings(
        _env_file=None,
        extraction_provider="gemini",
        extraction_api_key="generic-key",
        extraction_model="chosen-model",
    )
    assert settings.extraction_api_key.get_secret_value() == "generic-key"
    assert settings.extraction_model == "chosen-model"
    assert "generic-key" not in settings.model_dump_json()
    assert "vendor-key" not in settings.model_dump_json()
