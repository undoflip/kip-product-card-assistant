"""Клиент проверяется настоящим SDK поверх подставного транспорта: сеть не нужна."""

import json

import anthropic
import httpx2
import pytest

from app.errors import LLMError
from app.llm import DEFAULT_BASE_URL, DEFAULT_MODEL, ClaudeDrafter, create_drafter
from tests.helpers import make_draft


def message_response(text: str | None, stop_reason: str = "end_turn") -> dict:
    content = [{"type": "text", "text": text}] if text is not None else []
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": DEFAULT_MODEL,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def drafter_with(handler) -> ClaudeDrafter:
    client = anthropic.Anthropic(
        api_key="test-key",
        base_url="https://test.invalid",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return ClaudeDrafter(client, DEFAULT_MODEL)


def respond_with(status: int, body: dict | None = None):
    def handler(request):
        return httpx2.Response(status, json=body or {"type": "error", "error": {"type": "x", "message": "boom"}})

    return handler


def test_valid_response_becomes_draft():
    draft = make_draft()
    drafter = drafter_with(respond_with(200, message_response(draft.model_dump_json())))
    assert drafter("system", "user") == draft


def test_request_has_expected_shape():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx2.Response(200, json=message_response(make_draft().model_dump_json()))

    drafter_with(handler)("системный", "пользовательский")
    assert seen["model"] == DEFAULT_MODEL
    assert seen["system"] == "системный"
    assert seen["messages"] == [{"role": "user", "content": "пользовательский"}]
    assert seen["output_config"]["effort"] == "medium"
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in seen


@pytest.mark.parametrize(
    "status, code, http_status",
    [
        (400, "llm_bad_request", 502),
        (401, "llm_auth", 502),
        (403, "llm_auth", 502),
        (404, "llm_model_not_found", 502),
        (429, "llm_rate_limit", 429),
        (500, "llm_unavailable", 502),
        (529, "llm_unavailable", 502),
    ],
)
def test_api_errors_are_translated(status, code, http_status):
    with pytest.raises(LLMError) as exc:
        drafter_with(respond_with(status))("s", "u")
    assert exc.value.code == code
    assert exc.value.status == http_status


def test_connection_error_is_translated():
    def handler(request):
        raise httpx2.ConnectError("нет сети")

    with pytest.raises(LLMError) as exc:
        drafter_with(handler)("s", "u")
    assert exc.value.code == "llm_unavailable"


def test_timeout_is_translated():
    def handler(request):
        raise httpx2.ReadTimeout("долго")

    with pytest.raises(LLMError) as exc:
        drafter_with(handler)("s", "u")
    assert exc.value.code == "llm_unavailable"


def test_refusal_is_reported():
    with pytest.raises(LLMError) as exc:
        drafter_with(respond_with(200, message_response(None, "refusal")))("s", "u")
    assert exc.value.code == "llm_refusal"


def test_truncated_json_is_reported():
    body = message_response('{"seo_title": "обрезано', "max_tokens")
    with pytest.raises(LLMError) as exc:
        drafter_with(respond_with(200, body))("s", "u")
    assert exc.value.code == "llm_bad_response"


def test_json_that_does_not_match_schema_is_reported():
    with pytest.raises(LLMError) as exc:
        drafter_with(respond_with(200, message_response('{"seo_title": "x"}')))("s", "u")
    assert exc.value.code == "llm_bad_response"


def test_error_message_never_contains_the_key():
    with pytest.raises(LLMError) as exc:
        drafter_with(respond_with(401))("s", "u")
    assert "test-key" not in exc.value.message


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_key_gives_clear_error(monkeypatch, value):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    if value is not None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)
    with pytest.raises(LLMError) as exc:
        create_drafter()
    assert exc.value.code == "missing_api_key"
    assert exc.value.status == 503
    assert ".env" in exc.value.message


def test_ambient_base_url_is_ignored(monkeypatch):
    """Ключ не должен уйти на адрес из чужой переменной окружения."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.invalid")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert str(create_drafter().client.base_url).rstrip("/") == DEFAULT_BASE_URL


def test_model_and_base_url_can_be_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("LLM_BASE_URL", "https://proxy.test")
    drafter = create_drafter()
    assert drafter.model == "claude-sonnet-5-5"
    assert str(drafter.client.base_url).rstrip("/") == "https://proxy.test"


def test_rejected_request_reason_reaches_the_log(caplog):
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low"}}
    drafter = drafter_with(respond_with(400, body))
    with pytest.raises(LLMError), caplog.at_level("ERROR", logger="app.llm"):
        drafter("система", "пользователь")
    assert "credit balance is too low" in caplog.text
