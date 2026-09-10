import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.ingest.pipeline import IngestPipeline
from app.main import create_app
from app.rag.embedder import FakeEmbedder
from app.store.db import connect
from app.store.repository import ChunkRepository, ItemRepository


class RecordingQueue:
    """Captures submissions instead of running workers, so API tests stay deterministic."""

    def __init__(self) -> None:
        self.submitted: list[str] = []

    async def submit(self, item_id: str) -> None:
        self.submitted.append(item_id)


@pytest.fixture
async def context(tmp_path):
    conn = await connect(str(tmp_path / "api.db"))
    settings = Settings(
        _env_file=None, openai_api_key="test-key", chunk_target_tokens=100, chunk_overlap_tokens=20
    )
    items, chunks = ItemRepository(conn), ChunkRepository(conn)
    embedder = FakeEmbedder(dim=32)

    app = create_app()
    app.state.settings = settings
    app.state.items = items
    app.state.chunks = chunks
    app.state.embedder = embedder
    app.state.queue = RecordingQueue()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "app": app,
            "items": items,
            "chunks": chunks,
            "embedder": embedder,
            "settings": settings,
            "queue": app.state.queue,
            "pipeline": lambda fetch: IngestPipeline(
                items=items, chunks=chunks, embedder=embedder, settings=settings, fetch=fetch
            ),
        }

    await conn.close()
