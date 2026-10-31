from datetime import UTC, datetime

import httpx
import pytest

from foodbridge.agents.intake.extraction import extract_rules
from foodbridge.integrations.extraction import extract, strict_schema
from foodbridge.settings import Settings

NOW = datetime(2026, 10, 30, 20, tzinfo=UTC)
TEXT = (
    "Food: vegetable rice bowls. 20 meals, 10 kg. Refrigerated. Vegetarian. Allergens: soy. "
    "Today pickup 4 PM to 6 PM. Use by 8 PM."
)


def test_explicit_values_are_proposed_with_source_quotes():
    value = extract_rules(TEXT, "America/Los_Angeles", NOW)
    assert value.provider == "rules"
    assert value.fields.food_name == "vegetable rice bowls"
    assert value.fields.quantity_kg == 10
    assert value.fields.portions == 20
    assert value.fields.storage == "chilled"
    assert value.fields.allergens == ["soy"]
    assert value.fields.pickup_window.start.hour == 16
    assert value.fields.safe_use_by.hour == 20
    assert value.issues == []
    assert all(quote in TEXT for quote in value.evidence.values())


def test_missing_allergens_and_deadline_are_not_invented():
    value = extract_rules("20 meals from lunch", "America/Los_Angeles", NOW)
    assert value.fields.allergens is None
    assert value.fields.quantity_kg is None
    assert value.fields.safe_use_by is None
    assert {"allergens", "safe_use_by", "quantity_kg"} <= {i.field for i in value.issues}


def test_explicit_no_allergens_is_distinct_from_unknown():
    assert extract_rules("Allergens: none.", "UTC", NOW).fields.allergens == []
    assert extract_rules("Allergens: unknown.", "UTC", NOW).fields.allergens is None


@pytest.mark.parametrize(
    "text",
    [
        "Pickup 4 to 6 today. Use by 8.",
        "Pickup 4 PM to 6 PM. Use by 8 PM.",
        "Today pickup 6 PM to 4 PM. Use by 8 PM.",
        "Today pickup 4 PM to 6 PM. Tomorrow use by 8 PM.",
    ],
)
def test_ambiguous_times_require_review(text):
    value = extract_rules(text, "America/Los_Angeles", NOW)
    assert value.fields.pickup_window is None


def test_unit_conversion_is_explicit():
    assert extract_rules("2000 g", "UTC", NOW).fields.quantity_kg == 2


def test_unavailable_model_falls_back_without_leaking_credentials():
    settings = Settings(
        _env_file=None,
        ai_provider="openai",
        ai_model="test-model",
        ai_api_key="test-only-never-sent",
    )

    def handler(request):
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer test-only-never-sent"
        return httpx.Response(503)

    result = extract(TEXT, "UTC", NOW, settings, httpx.MockTransport(handler))
    assert result.provider == "rules"
    assert any(issue.code == "provider_unavailable" for issue in result.issues)
    assert "test-only-never-sent" not in result.model_dump_json()


def test_model_must_cite_real_source_text():
    import json

    settings = Settings(
        _env_file=None,
        ai_provider="openai",
        ai_model="test-model",
        ai_api_key="test-only-never-sent",
    )
    proposal = {
        "fields": {"quantity_kg": 99, "allergens": []},
        "evidence": [{"field": "quantity_kg", "quote": "imaginary 99 kg"}],
    }

    def handler(request):
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(proposal)}],
                    }
                ],
            },
        )

    result = extract(TEXT, "UTC", NOW, settings, httpx.MockTransport(handler))
    assert result.provider == "openai"
    assert result.fields.quantity_kg is None
    assert result.fields.allergens is None
    assert any(issue.code == "source_mismatch" for issue in result.issues)


def test_model_schema_has_no_implicit_optional_properties():
    def visit(value):
        if isinstance(value, dict):
            assert "default" not in value
            if value.get("type") == "object" and "properties" in value:
                assert set(value["required"]) == set(value["properties"])
                assert value["additionalProperties"] is False
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(strict_schema())


def test_empty_or_unrecognized_allergen_declaration_is_not_none():
    assert extract_rules("Allergens: ,.", "UTC", NOW).fields.allergens is None
    assert extract_rules("Allergens: may contain soy.", "UTC", NOW).fields.allergens is None
