import httpx
import pytest

from app.config import Settings
from app.errors import ApiError
from app.ingest.pipeline import IngestPipeline, recover_pending
from app.ingest.queue import IngestQueue
from app.rag.embedder import FakeEmbedder
from app.store.db import connect
from app.store.repository import ChunkRepository, ItemRepository

ARTICLE = (
    "<html><head><title>Rebalancing</title></head><body><article>"
    "<p>A rebalance is triggered when consumer group membership changes.</p>"
    "<p>The coordinator revokes partitions and reassigns them across members.</p>"
    "</article></body></html>"
)


@pytest.fixture
async def wiring(tmp_path):
    conn = await connect(str(tmp_path / "pipeline.db"))
    items, chunks = ItemRepository(conn), ChunkRepository(conn)
    settings = Settings(_env_file=None, chunk_target_tokens=100, chunk_overlap_tokens=20)
    yield items, chunks, settings
    await conn.close()


def pipeline_with(items, chunks, settings, fetch):
    return IngestPipeline(
        items=items, chunks=chunks, embedder=FakeEmbedder(dim=32), settings=settings, fetch=fetch
    )


async def _unused_fetch(*args, **kwargs):
    raise AssertionError("a note must not trigger a fetch")


async def test_a_note_becomes_ready_with_chunks(wiring):
    items, chunks, settings = wiring
    item = await items.create(
        type="note", source_url=None, title="Kafka", raw_content="Rebalance happens on rejoin."
    )

    await pipeline_with(items, chunks, settings, _unused_fetch).process(item.id)

    reloaded = await items.get(item.id)
    assert reloaded.status == "ready"
    assert reloaded.error is None
    assert reloaded.chunk_count == 1


async def test_a_url_is_fetched_extracted_and_titled(wiring):
    items, chunks, settings = wiring
    item = await items.create(
        type="url", source_url="https://example.com/kafka", title=None, raw_content=None
    )

    async def fetch(url, **kwargs):
        return url, ARTICLE

    await pipeline_with(items, chunks, settings, fetch).process(item.id)

    reloaded = await items.get(item.id)
    assert reloaded.status == "ready"
    assert reloaded.title == "Rebalancing"
    assert "membership changes" in reloaded.raw_content


async def test_a_fetch_failure_marks_the_item_failed_with_a_readable_reason(wiring):
    items, chunks, settings = wiring
    item = await items.create(
        type="url", source_url="https://example.com/gone", title=None, raw_content=None
    )

    async def fetch(url, **kwargs):
        raise ApiError("fetch_failed", "Upstream returned HTTP 404.", 502)

    await pipeline_with(items, chunks, settings, fetch).process(item.id)

    reloaded = await items.get(item.id)
    assert reloaded.status == "failed"
    assert reloaded.error == "Upstream returned HTTP 404."
    assert reloaded.chunk_count == 0


async def test_an_unreadable_page_fails_as_extraction_empty(wiring):
    items, chunks, settings = wiring
    item = await items.create(
        type="url", source_url="https://example.com/spa", title=None, raw_content=None
    )

    async def fetch(url, **kwargs):
        return url, "<html><body><nav>Menu</nav></body></html>"

    await pipeline_with(items, chunks, settings, fetch).process(item.id)

    assert "readable text" in (await items.get(item.id)).error


async def test_a_transient_failure_is_retried_once_then_succeeds(wiring):
    items, chunks, settings = wiring
    item = await items.create(
        type="url", source_url="https://example.com/flaky", title=None, raw_content=None
    )
    attempts = 0

    async def fetch(url, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("first attempt times out")
        return url, ARTICLE

    pipeline = pipeline_with(items, chunks, settings, fetch)
    pipeline.retry_delay_s = 0
    await pipeline.process(item.id)

    assert attempts == 2
    assert (await items.get(item.id)).status == "ready"


async def test_a_permanent_failure_is_not_retried(wiring):
    items, chunks, settings = wiring
    item = await items.create(
        type="url", source_url="https://example.com/x", title=None, raw_content=None
    )
    attempts = 0

    async def fetch(url, **kwargs):
        nonlocal attempts
        attempts += 1
        raise ApiError("blocked_host", "Refusing to fetch a non-public address.", 400)

    pipeline = pipeline_with(items, chunks, settings, fetch)
    pipeline.retry_delay_s = 0
    await pipeline.process(item.id)

    assert attempts == 1
    assert (await items.get(item.id)).status == "failed"


async def test_processing_a_missing_item_is_a_no_op(wiring):
    items, chunks, settings = wiring

    await pipeline_with(items, chunks, settings, _unused_fetch).process("itm_ghost")


async def test_recover_pending_requeues_stuck_items(wiring):
    items, _, _ = wiring
    stuck = await items.create(type="note", source_url=None, title="s", raw_content="body")
    done = await items.create(type="note", source_url=None, title="d", raw_content="body")
    await items.mark_ready(done.id)

    submitted: list[str] = []
    queue = IngestQueue(handler=lambda item_id: _noop(), workers=1)
    queue.submit = lambda item_id: _capture(submitted, item_id)

    count = await recover_pending(items, queue)

    assert count == 1
    assert submitted == [stuck.id]


async def _noop() -> None:
    return None


async def _capture(sink: list[str], item_id: str) -> None:
    sink.append(item_id)
