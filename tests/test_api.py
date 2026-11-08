import json

import pytest
from fastapi.testclient import TestClient

from app.errors import LLMError
from app.main import MAX_BODY_BYTES, create_app
from tests.helpers import FakeDrafter, make_draft

VALID = {
    "name": "Манометр показывающий DM 02",
    "manufacturer": "Манотомь",
    "specs": {
        "диапазон измерений": "0–1,6 МПа",
        "класс точности": "1,5",
        "присоединение": "G1/2",
        "диаметр корпуса": "100 мм",
    },
    "description": "Прибор предназначен для измерения избыточного давления неагрессивных сред.",
}


@pytest.fixture(autouse=True)
def default_allowed_hosts(monkeypatch):
    """main.py загружает локальный файл окружения: тесты не зависят от ALLOWED_HOSTS разработчика."""
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)


def client_with(*responses) -> tuple[TestClient, FakeDrafter]:
    drafter = FakeDrafter(*responses)
    return TestClient(
        create_app(lambda: drafter), base_url="http://localhost", raise_server_exceptions=False
    ), drafter


def post(client: TestClient, body):
    content = body if isinstance(body, (bytes, str)) else json.dumps(body, ensure_ascii=False)
    return client.post(
        "/api/generate", content=content, headers={"Content-Type": "application/json"}
    )


def test_page_is_served():
    client, _ = client_with()
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_valid_product_returns_card_and_markdown():
    client, _ = client_with(make_draft())
    response = post(client, VALID)
    assert response.status_code == 200
    body = response.json()
    assert body["card"]["status"] == "ok"
    assert body["card"]["seo_title"] == make_draft().seo_title
    assert body["markdown"].startswith("# ")


@pytest.mark.parametrize(
    "raw",
    ["{broken", "", b"\xff\xfe", "[" * 90_000, b'{"name": "\x5cud800"}'],
    ids=["broken", "empty", "not_utf8", "deep_nesting", "lone_surrogate"],
)
def test_broken_json_returns_400_without_calling_llm(raw):
    client, drafter = client_with()
    response = post(client, raw)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"
    assert drafter.calls == []


@pytest.mark.parametrize(
    "body, code",
    [
        ([VALID], "invalid_structure"),
        ({**VALID, "specs": ["x"]}, "invalid_structure"),
        ({**VALID, "name": ""}, "insufficient_data"),
        ({"name": "Манометр", "specs": {}, "description": ""}, "insufficient_data"),
        ({**VALID, "name": "12345"}, "insufficient_data"),
        ({"name": "Манометр", "specs": {"321": "543"}, "description": "2435"}, "insufficient_data"),
    ],
)
def test_unusable_input_returns_422_without_calling_llm(body, code):
    client, drafter = client_with()
    response = post(client, body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert drafter.calls == []


def test_field_errors_name_the_field():
    client, _ = client_with()
    details = post(client, {**VALID, "specs": ["x"]}).json()["error"]["details"]
    assert any("specs" in detail for detail in details)


def test_oversized_body_is_rejected():
    client, drafter = client_with()
    response = post(client, {**VALID, "description": "ы" * MAX_BODY_BYTES})
    assert response.status_code == 413
    assert drafter.calls == []


def test_missing_key_is_reported_on_request_not_on_startup():
    def no_key():
        raise LLMError("missing_api_key", 503, "Не задан ANTHROPIC_API_KEY.")

    client = TestClient(create_app(no_key), base_url="http://localhost")
    assert client.get("/").status_code == 200
    response = post(client, VALID)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "missing_api_key"


@pytest.mark.parametrize(
    "code, status", [("llm_auth", 502), ("llm_rate_limit", 429), ("llm_unavailable", 502)]
)
def test_llm_errors_keep_their_status(code, status):
    client, _ = client_with(LLMError(code, status, "Сообщение."))
    response = post(client, VALID)
    assert response.status_code == status
    assert response.json()["error"] == {"code": code, "message": "Сообщение.", "details": []}


def test_unexpected_error_returns_json_without_details():
    client, _ = client_with(RuntimeError("секрет во внутренней ошибке"))
    response = post(client, VALID)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "секрет" not in response.text


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data"]
)
def test_cross_site_form_types_do_not_reach_the_model(content_type):
    client, drafter = client_with(make_draft())
    response = client.post(
        "/api/generate",
        content=json.dumps(VALID, ensure_ascii=False),
        headers={"Content-Type": content_type},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert drafter.calls == []


def test_json_content_type_with_charset_is_accepted():
    client, _ = client_with(make_draft())
    response = client.post(
        "/api/generate",
        content=json.dumps(VALID, ensure_ascii=False),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 200


def test_preflight_from_other_origin_is_not_allowed():
    client, _ = client_with(make_draft())
    response = client.options(
        "/api/generate",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in response.headers


def post_with_headers(client: TestClient, **headers):
    return client.post(
        "/api/generate",
        content=json.dumps(VALID, ensure_ascii=False),
        headers={"Content-Type": "application/json", **headers},
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Host": "evil.example:8000"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
    ],
)
def test_foreign_host_or_origin_does_not_reach_the_model(headers):
    client, drafter = client_with(make_draft())
    response = post_with_headers(client, **headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_host"
    assert drafter.calls == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Host": "localhost:8000"},
        {"Host": "127.0.0.1:8000"},
        {"Origin": "http://localhost:8000"},
        {"Origin": "http://127.0.0.1:8000"},
    ],
)
def test_local_requests_are_accepted(headers):
    client, _ = client_with(make_draft())
    assert post_with_headers(client, **headers).status_code == 200


def test_allowed_hosts_can_be_configured(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "cards.example, localhost")
    client, _ = client_with(make_draft())
    assert post_with_headers(client, Host="cards.example").status_code == 200
    assert post_with_headers(client, Host="127.0.0.1").status_code == 403


@pytest.mark.parametrize("allowed", ["localhost:8000", "[::1], LOCALHOST"])
def test_allowed_hosts_entries_may_include_port_or_ipv6(monkeypatch, allowed):
    monkeypatch.setenv("ALLOWED_HOSTS", allowed)
    client, _ = client_with(make_draft())
    assert post_with_headers(client, Host="localhost:8000").status_code == 200
    assert post_with_headers(client, Host="evil.example").status_code == 403
