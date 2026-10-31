"""App-wide structured AI client. All model-backed features share one resolved configuration."""

import json
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from foodbridge.observability import model_calls
from foodbridge.settings import Settings


def provider_schema(schema: dict, provider: str) -> dict:
    """Strip Claude's unsupported constraints; Pydantic still enforces them locally."""
    schema = json.loads(json.dumps(schema))
    if provider == "anthropic":

        def visit(node):
            if isinstance(node, dict):
                constraints = {}
                for key in (
                    "minimum",
                    "maximum",
                    "exclusiveMinimum",
                    "exclusiveMaximum",
                    "minLength",
                    "maxLength",
                    "multipleOf",
                    "pattern",
                ):
                    if key in node:
                        constraints[key] = node.pop(key)
                if constraints:
                    node["description"] = (
                        f"{node.get('description', '')} Constraints: {constraints}"
                    )
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(schema)
    return schema


def _request_json(
    client: httpx.Client, settings: Settings, instructions: str, user_input: str, schema: dict
) -> str:
    provider = settings.ai_provider
    key = settings.ai_api_key.get_secret_value()
    schema = provider_schema(schema, provider)
    model = settings.ai_model
    if provider == "openai":
        response = client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "store": False,
                "instructions": instructions,
                "input": user_input,
                "max_output_tokens": 2000,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "foodbridge_result",
                        "strict": True,
                        "schema": schema,
                    }
                },
            },
        )
    elif provider == "gemini":
        response = client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(model, safe='')}:generateContent",
            headers={"x-goog-api-key": key},
            json={
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": [{"text": user_input}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                    "maxOutputTokens": 4096,
                },
            },
        )
    elif provider == "anthropic":
        response = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": model,
                "max_tokens": 2000,
                "system": instructions,
                "messages": [{"role": "user", "content": user_input}],
                "output_config": {"format": {"type": "json_schema", "schema": schema}},
            },
        )
    elif provider == "openai_compatible":
        response_format = {"type": settings.ai_response_format}
        if settings.ai_response_format == "json_schema":
            response_format["json_schema"] = {
                "name": "foodbridge_result",
                "strict": True,
                "schema": schema,
            }
        response = client.post(
            settings.ai_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "max_tokens": 2000,
                "response_format": response_format,
                "messages": [
                    {
                        "role": "system",
                        "content": instructions + " Return JSON matching: " + json.dumps(schema),
                    },
                    {"role": "user", "content": user_input},
                ],
            },
        )
    else:
        raise ValueError("unsupported provider")
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("invalid provider response")
    if provider == "openai":
        if body.get("status") != "completed":
            raise ValueError("incomplete output")
        parts = [
            part
            for item in body.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
        ]
        if any(part.get("type") == "refusal" for part in parts):
            raise ValueError("refused output")
        return "".join(part["text"] for part in parts if part.get("type") == "output_text")
    if provider == "gemini":
        if body.get("promptFeedback", {}).get("blockReason"):
            raise ValueError("blocked prompt")
        candidates = body.get("candidates", [])
        if len(candidates) != 1 or candidates[0].get("finishReason") != "STOP":
            raise ValueError("blocked or incomplete output")
        return "".join(
            part["text"]
            for part in candidates[0]["content"]["parts"]
            if "text" in part and not part.get("thought")
        )
    if provider == "anthropic":
        if body.get("stop_reason") != "end_turn":
            raise ValueError("refused or incomplete output")
        return "".join(part["text"] for part in body["content"] if part.get("type") == "text")
    choices = body.get("choices", [])
    if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
        raise ValueError("incomplete output")
    message = choices[0]["message"]
    if message.get("refusal") or message.get("tool_calls"):
        raise ValueError("refused output")
    return message["content"]


def schema_for_model(output_type: type[BaseModel]) -> dict:
    schema = output_type.model_json_schema()

    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def generate_structured[Output: BaseModel](
    settings: Settings,
    *,
    instructions: str,
    user_input: str,
    output_type: type[Output],
    transport: httpx.BaseTransport | None = None,
) -> Output:
    """Use the single app provider/key/model; features supply prompts and output types only.

    Raises on disabled AI, provider failures or invalid output. The feature owns an
    explicit deterministic fallback. Never switches provider or credentials on failure.
    """
    if settings.ai_provider == "rules":
        raise ValueError("App AI is disabled")
    with httpx.Client(timeout=settings.ai_timeout_s, transport=transport) as client:
        for attempt in range(2):
            try:
                output = _request_json(
                    client, settings, instructions, user_input, schema_for_model(output_type)
                )
                value = output_type.model_validate_json(output)
                model_calls.labels("completed").inc()
                return value
            except (httpx.TimeoutException, httpx.NetworkError):
                model_calls.labels("transient_error").inc()
                if attempt:
                    raise
            except httpx.HTTPStatusError as exc:
                model_calls.labels("http_error").inc()
                if attempt or exc.response.status_code < 500:
                    raise
            except ValueError:
                model_calls.labels("invalid_output").inc()
                raise
    raise ValueError("model attempts exhausted")
