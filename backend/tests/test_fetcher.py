import socket

import httpx
import pytest

from app.errors import ApiError
from app.ingest import fetcher as fetcher_module
from app.ingest.fetcher import safe_fetch

# Hostname -> resolved addresses. Literal-IP URLs bypass _resolve entirely via
# the _is_ip short-circuit, so only named hosts need an entry here.
_FAKE_DNS = {
    "example.com": ["93.184.216.34"],
    "localhost": ["127.0.0.1"],
    "internal.test": ["10.1.2.3"],
}


@pytest.fixture(autouse=True)
def no_real_dns(monkeypatch):
    """No test in this module resolves a real hostname."""

    def fake_resolve(host: str) -> list[str]:
        if host not in _FAKE_DNS:
            raise socket.gaierror(f"unmapped host in tests: {host}")
        return _FAKE_DNS[host]

    monkeypatch.setattr(fetcher_module, "_resolve", fake_resolve)


def client_returning(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


async def test_fetches_a_public_html_page():
    def handler(request):
        return httpx.Response(200, html="<html><body><p>Hello</p></body></html>")

    async with client_returning(handler) as client:
        final_url, body = await safe_fetch(
            "https://example.com/a", timeout_s=5, max_bytes=1000, client=client
        )

    assert final_url == "https://example.com/a"
    assert "Hello" in body


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/x",
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://[::1]/x",
    ],
)
async def test_refuses_non_public_addresses(url):
    with pytest.raises(ApiError) as caught:
        await safe_fetch(url, timeout_s=5, max_bytes=1000)

    assert caught.value.code == "blocked_host"
    assert caught.value.http_status == 400


async def test_refuses_a_hostname_that_resolves_to_a_private_address():
    """The name looks public; only resolution reveals it is internal."""
    with pytest.raises(ApiError) as caught:
        await safe_fetch("https://internal.test/secrets", timeout_s=5, max_bytes=1000)

    assert caught.value.code == "blocked_host"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x/1"])
async def test_refuses_non_http_schemes(url):
    with pytest.raises(ApiError) as caught:
        await safe_fetch(url, timeout_s=5, max_bytes=1000)

    assert caught.value.code == "unsupported_scheme"


async def test_revalidates_each_redirect_hop():
    def handler(request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/"})
        return httpx.Response(200, text="secrets")

    async with client_returning(handler) as client:
        with pytest.raises(ApiError) as caught:
            await safe_fetch(
                "https://example.com/start", timeout_s=5, max_bytes=1000, client=client
            )

    assert caught.value.code == "blocked_host"


async def test_follows_a_public_redirect_and_reports_the_final_url():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "https://example.com/final"})
        return httpx.Response(200, html="<p>arrived</p>")

    async with client_returning(handler) as client:
        final_url, body = await safe_fetch(
            "https://example.com/start", timeout_s=5, max_bytes=1000, client=client
        )

    assert final_url == "https://example.com/final"
    assert "arrived" in body


async def test_a_relative_redirect_resolves_against_the_current_url():
    def handler(request):
        if request.url.path == "/a/start":
            return httpx.Response(302, headers={"location": "../final"})
        return httpx.Response(200, html="<p>arrived</p>")

    async with client_returning(handler) as client:
        final_url, body = await safe_fetch(
            "https://example.com/a/start", timeout_s=5, max_bytes=1000, client=client
        )

    assert final_url == "https://example.com/final"
    assert "arrived" in body


async def test_a_redirect_without_a_location_header_fails():
    def handler(request):
        return httpx.Response(302, headers={})

    async with client_returning(handler) as client:
        with pytest.raises(ApiError) as caught:
            await safe_fetch("https://example.com/x", timeout_s=5, max_bytes=1000, client=client)

    assert caught.value.code == "fetch_failed"


async def test_gives_up_after_too_many_redirects():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://example.com/loop"})

    async with client_returning(handler) as client:
        with pytest.raises(ApiError) as caught:
            await safe_fetch(
                "https://example.com/loop", timeout_s=5, max_bytes=1000, client=client
            )

    assert caught.value.code == "too_many_redirects"


async def test_rejects_a_body_over_the_cap():
    def handler(request):
        return httpx.Response(200, html="<p>" + "x" * 5000 + "</p>")

    async with client_returning(handler) as client:
        with pytest.raises(ApiError) as caught:
            await safe_fetch("https://example.com/big", timeout_s=5, max_bytes=100, client=client)

    assert caught.value.code == "too_large"


async def test_rejects_unexpected_content_types():
    def handler(request):
        return httpx.Response(
            200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
        )

    async with client_returning(handler) as client:
        with pytest.raises(ApiError) as caught:
            await safe_fetch(
                "https://example.com/f.pdf", timeout_s=5, max_bytes=1000, client=client
            )

    assert caught.value.code == "unsupported_content_type"


async def test_rejects_a_response_with_no_content_type():
    """Fail closed: if the server will not say what it sent, do not ingest it."""

    def handler(request):
        return httpx.Response(200, content=b"who knows", headers={})

    async with client_returning(handler) as client:
        with pytest.raises(ApiError) as caught:
            await safe_fetch("https://example.com/x", timeout_s=5, max_bytes=1000, client=client)

    assert caught.value.code == "unsupported_content_type"


async def test_upstream_error_status_is_a_502():
    def handler(request):
        return httpx.Response(503, text="down")

    async with client_returning(handler) as client:
        with pytest.raises(ApiError) as caught:
            await safe_fetch("https://example.com/x", timeout_s=5, max_bytes=1000, client=client)

    assert caught.value.code == "fetch_failed"
    assert caught.value.http_status == 502
