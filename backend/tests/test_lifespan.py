"""Drives the real FastAPI lifespan, since ASGITransport never sends lifespan
events and every other test fixture sets app.state by hand. This is the only
test that actually executes `lifespan`, `build_embedder`, and the
`recover_pending` call site in main.py.
"""

from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.config import Settings
from app.main import create_app

_STATE_KEYS = ("settings", "items", "chunks", "embedder", "queue", "retriever", "answerer")


def _patch_settings(monkeypatch, tmp_path) -> Settings:
    settings = Settings(
        _env_file=None, openai_api_key="test-key", db_path=str(tmp_path / "lifespan.db")
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    return settings


async def test_lifespan_wires_app_state_and_shuts_workers_down_cleanly(monkeypatch, tmp_path):
    settings = _patch_settings(monkeypatch, tmp_path)
    app = create_app()

    async with app.router.lifespan_context(app):
        for key in _STATE_KEYS:
            assert hasattr(app.state, key), f"app.state.{key} was never set"
        assert app.state.settings is settings
        assert app.state.queue.worker_count == settings.ingest_workers

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/health")
        assert res.status_code == 200

    assert app.state.queue.worker_count == 0
