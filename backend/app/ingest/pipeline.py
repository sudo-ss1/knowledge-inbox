import asyncio
from collections.abc import Awaitable, Callable

import httpx

from ..config import Settings
from ..errors import ApiError
from ..logging import get_logger
from ..rag.chunker import chunk_text
from ..rag.embedder import Embedder
from ..store.repository import ChunkRepository, ItemRepository
from .extractor import extract
from .fetcher import safe_fetch
from .queue import IngestQueue

log = get_logger(__name__)

Fetcher = Callable[..., Awaitable[tuple[str, str]]]

_TRANSIENT_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    if isinstance(exc, ApiError):
        return exc.http_status >= 500
    return getattr(exc, "status_code", None) in {429, 500, 502, 503, 504}


class IngestPipeline:
    """Fetch, extract, chunk, embed, store. One item at a time."""

    def __init__(
        self,
        *,
        items: ItemRepository,
        chunks: ChunkRepository,
        embedder: Embedder,
        settings: Settings,
        fetch: Fetcher = safe_fetch,
    ) -> None:
        self._items = items
        self._chunks = chunks
        self._embedder = embedder
        self._settings = settings
        self._fetch = fetch
        self.retry_delay_s = 2.0

    async def process(self, item_id: str) -> None:
        item = await self._items.get(item_id)
        if item is None:
            log.warning("ingest_item_missing", item_id=item_id)
            return

        try:
            title, text = await self._resolve_content(item)
            await self._items.set_content(item_id, title=title, raw_content=text)

            chunks = chunk_text(
                text,
                target_tokens=self._settings.chunk_target_tokens,
                overlap_tokens=self._settings.chunk_overlap_tokens,
            )
            if not chunks:
                raise ApiError("empty_content", "There was nothing indexable in that content.", 422)
            log.info(
                "chunked",
                item_id=item_id,
                chunks=len(chunks),
                tokens=sum(c.token_count for c in chunks),
            )

            vectors = await self._retry(lambda: self._embedder.embed([c.text for c in chunks]))
            await self._chunks.insert_many(item_id, chunks, vectors, self._embedder.model)
            await self._items.mark_ready(item_id)
            log.info("item_ready", item_id=item_id, chunks=len(chunks))

        except Exception as exc:
            reason = (
                exc.message if isinstance(exc, ApiError) else "Unexpected failure while indexing."
            )
            await self._items.mark_failed(item_id, reason)
            log.error("item_failed", exc_info=exc, item_id=item_id, reason=reason)

    async def _resolve_content(self, item) -> tuple[str | None, str]:
        if item.type == "note":
            return item.title, item.raw_content or ""

        final_url, html = await self._retry(
            lambda: self._fetch(
                item.source_url,
                timeout_s=self._settings.fetch_timeout_s,
                max_bytes=self._settings.fetch_max_bytes,
            )
        )
        return extract(html, final_url)

    async def _retry(self, operation: Callable[[], Awaitable]):
        """One retry on transient failure. No dead-letter queue, no backoff ladder."""
        try:
            return await operation()
        except Exception as exc:
            if not _is_transient(exc):
                raise
            log.warning("ingest_retrying", reason=type(exc).__name__)
            await asyncio.sleep(self.retry_delay_s)
            return await operation()


async def recover_pending(items: ItemRepository, queue: IngestQueue) -> int:
    """Re-enqueue anything left pending by a restart.

    Queued work survives a restart; work that was mid-flight starts over.
    """
    pending = await items.pending_ids()
    for item_id in pending:
        await queue.submit(item_id)
    if pending:
        log.info("recovered_pending_items", count=len(pending))
    return len(pending)
