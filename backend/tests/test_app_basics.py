import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.errors import ApiError
from app.logging import configure_logging, get_logger, request_id_var
from app.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_returns_ok(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_response_carries_request_id(client):
    res = await client.get("/health")
    assert res.headers["x-request-id"].startswith("req_")


async def test_inbound_request_id_is_honored(client):
    res = await client.get("/health", headers={"X-Request-Id": "req_caller123"})
    assert res.headers["x-request-id"] == "req_caller123"


async def test_api_error_renders_the_envelope(client):
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise ApiError("teapot", "I am a teapot.", 418)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/boom", headers={"X-Request-Id": "req_zz"})

    assert res.status_code == 418
    assert res.json() == {
        "error": {"code": "teapot", "message": "I am a teapot.", "request_id": "req_zz"}
    }


async def test_unknown_path_uses_the_envelope(client):
    res = await client.get("/nope")
    assert res.status_code == 404
    assert set(res.json()["error"]) == {"code", "message", "request_id"}


def test_logs_are_single_line_json_with_request_id(capsys):
    configure_logging("INFO")
    token = request_id_var.set("req_test")
    try:
        get_logger("t").info("item_ready", item_id="itm_1", chunks=3)
    finally:
        request_id_var.reset(token)

    line = capsys.readouterr().out.strip()
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["event"] == "item_ready"
    assert payload["request_id"] == "req_test"
    assert payload["item_id"] == "itm_1"
    assert payload["chunks"] == 3
