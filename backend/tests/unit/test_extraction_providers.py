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
        if name.startswith(("FOODBRIDGE_AI_", "FOODBRIDGE_EXTRACTION_")) or name in {
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
        ai_provider=provider,
        ai_model="test-model",
        ai_api_key="private-test-key",
        ai_base_url="https://example.test/v1" if provider == "openai_compatible" else None,
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
        assert settings.ai_provider == provider
        assert settings.ai_model
        assert settings.ai_api_key.get_secret_value() == "private-test-key"
    monkeypatch.setenv(variable, "private-test-key")
    assert Settings(_env_file=None).ai_provider == provider


def test_no_key_rules_opt_out_and_ambiguous_keys(monkeypatch):
    assert Settings(_env_file=None).ai_provider == "rules"
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    with pytest.raises(ValidationError, match="ambiguous"):
        Settings(_env_file=None)
    assert Settings(_env_file=None, ai_provider="rules").ai_provider == "rules"
    chosen = Settings(_env_file=None, ai_provider="gemini")
    assert chosen.ai_api_key.get_secret_value() == "gemini-test-key"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ai_provider": "gemini"},
        {"ai_api_key": "private-test-key"},
        {"ai_provider": "openai_compatible", "ai_api_key": "private-test-key"},
        {
            "ai_provider": "openai_compatible",
            "ai_api_key": "private-test-key",
            "ai_model": "model",
            "ai_base_url": "http://example.test/v1",
        },
        {"ai_provider": "openai", "ai_api_key": " "},
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
        configured("openai_compatible", ai_response_format="json_object"),
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
        Settings(_env_file=None, ai_provider="gemini")


def test_generic_key_and_model_override_vendor_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "vendor-key")
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_api_key="generic-key",
        ai_model="chosen-model",
    )
    assert settings.ai_api_key.get_secret_value() == "generic-key"
    assert settings.ai_model == "chosen-model"
    assert "generic-key" not in settings.model_dump_json()
    assert "vendor-key" not in settings.model_dump_json()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_different_features_share_one_provider_key_and_model(provider):
    from pydantic import BaseModel, ConfigDict

    from foodbridge.integrations.ai import generate_structured

    class Summary(BaseModel):
        model_config = ConfigDict(extra="forbid")
        summary: str

    class Ranking(BaseModel):
        model_config = ConfigDict(extra="forbid")
        candidate_ids: list[str]

    settings = configured(provider)
    requests = []

    def handler(request):
        requests.append(request)
        text = '{"summary":"review required"}' if len(requests) == 1 else '{"candidate_ids":["a"]}'
        return httpx.Response(200, json=response_body(provider, text))

    # Different prompts/schemas stand in for future features, not implemented matching.
    transport = httpx.MockTransport(handler)
    summary = generate_structured(
        settings,
        instructions="Summarize supplied facts.",
        user_input="facts",
        output_type=Summary,
        transport=transport,
    )
    ranking = generate_structured(
        settings,
        instructions="Rank only supplied IDs.",
        user_input="a",
        output_type=Ranking,
        transport=transport,
    )
    assert summary.summary == "review required"
    assert ranking.candidate_ids == ["a"]
    assert requests[0].url == requests[1].url
    for request in requests:
        header = (
            "x-goog-api-key"
            if provider == "gemini"
            else ("x-api-key" if provider == "anthropic" else "authorization")
        )
        assert request.headers[header].endswith("private-test-key")
        if provider != "gemini":
            assert json.loads(request.content)["model"] == settings.ai_model


def test_global_settings_win_over_legacy_aliases_for_all_consumers(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "FOODBRIDGE_AI_PROVIDER=gemini\nFOODBRIDGE_AI_API_KEY=global-key\n"
        "FOODBRIDGE_AI_MODEL=global-model\nFOODBRIDGE_EXTRACTION_PROVIDER=anthropic\n"
        "FOODBRIDGE_EXTRACTION_API_KEY=old-key\nFOODBRIDGE_EXTRACTION_MODEL=old-model\n"
    )
    settings = Settings(_env_file=path)
    assert settings.ai_provider == "gemini"
    assert settings.ai_model == "global-model"
    assert settings.ai_api_key.get_secret_value() == "global-key"
    assert not hasattr(settings, "extraction_provider")


def test_legacy_settings_resolve_to_global_configuration(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "FOODBRIDGE_EXTRACTION_PROVIDER=anthropic\n"
        "FOODBRIDGE_EXTRACTION_API_KEY=legacy-key\n"
        "FOODBRIDGE_EXTRACTION_MODEL=legacy-model\n"
    )
    settings = Settings(_env_file=path)
    assert settings.ai_provider == "anthropic"
    assert settings.ai_model == "legacy-model"
    assert settings.ai_api_key.get_secret_value() == "legacy-key"


def test_shared_client_cannot_call_remote_models_when_app_ai_is_disabled():
    from pydantic import BaseModel

    from foodbridge.integrations.ai import generate_structured

    class Output(BaseModel):
        value: str

    def handler(request):
        pytest.fail("disabled app AI must not contact any provider")

    with pytest.raises(ValueError, match="disabled"):
        generate_structured(
            Settings(_env_file=None, ai_provider="rules"),
            instructions="test",
            user_input="test",
            output_type=Output,
            transport=httpx.MockTransport(handler),
        )
