"""Server-side fetching of a user-supplied URL is an SSRF surface.

Every hop is revalidated because redirecting into an internal address is the
standard bypass for a check that only inspects the URL the user typed.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from ..errors import ApiError
from ..logging import get_logger

log = get_logger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
MAX_REDIRECTS = 3
USER_AGENT = "knowledge-inbox/0.1 (+https://github.com/sudo-ss1/knowledge-inbox)"


def assert_public_host(host: str) -> None:
    stripped = host.strip("[]")
    try:
        candidates = [stripped] if _is_ip(stripped) else _resolve(stripped)
    except socket.gaierror as exc:
        raise ApiError("dns_failed", f"Could not resolve host '{host}'.", 502) from exc

    for address in candidates:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ApiError(
                "blocked_host",
                f"Refusing to fetch '{host}' because it resolves to a non-public address.",
                400,
            )


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ApiError(
            "unsupported_scheme",
            f"Only http and https URLs are supported, got '{parsed.scheme or 'none'}'.",
            400,
        )
    if not parsed.hostname:
        raise ApiError("bad_request", "That URL has no host.", 400)
    assert_public_host(parsed.hostname)


async def safe_fetch(
    url: str,
    *,
    timeout_s: float,
    max_bytes: int,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=timeout_s, follow_redirects=False, headers={"User-Agent": USER_AGENT}
    )
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            _validate_url(current)
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ApiError("fetch_failed", "Redirect without a Location header.", 502)
                    current = str(httpx.URL(current).join(location))
                    continue
                if response.status_code >= 400:
                    raise ApiError(
                        "fetch_failed", f"Upstream returned HTTP {response.status_code}.", 502
                    )
                _assert_supported_type(response)
                body = await _read_capped(response, max_bytes)

            log.info("fetch_completed", bytes=len(body), url_host=urlparse(current).hostname)
            return current, body.decode(response.encoding or "utf-8", errors="replace")

        raise ApiError("too_many_redirects", f"More than {MAX_REDIRECTS} redirects.", 502)
    finally:
        if owns_client:
            await client.aclose()


def _assert_supported_type(response: httpx.Response) -> None:
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not content_type:
        raise ApiError(
            "unsupported_content_type",
            "That server did not declare a content type.",
            400,
        )
    if not content_type.startswith(ALLOWED_CONTENT_TYPES):
        raise ApiError(
            "unsupported_content_type",
            f"Expected HTML or plain text, got '{content_type}'.",
            400,
        )


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    buffer = bytearray()
    async for piece in response.aiter_bytes():
        buffer.extend(piece)
        if len(buffer) > max_bytes:
            raise ApiError("too_large", f"That page is larger than {max_bytes} bytes.", 400)
    return bytes(buffer)
