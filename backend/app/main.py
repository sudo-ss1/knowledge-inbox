from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_items import router as items_router
from .api.routes_query import router as query_router
from .config import get_settings
from .errors import install_error_handlers
from .ingest.pipeline import IngestPipeline, recover_pending
from .ingest.queue import IngestQueue
from .logging import configure_logging, get_logger
from .middleware import RequestContextMiddleware
from .rag.answerer import Answerer, OpenAILlm
from .rag.embedder import build_embedder
from .rag.retriever import Retriever
from .store.db import connect
from .store.repository import ChunkRepository, ItemRepository

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    conn = await connect(settings.db_path)
    items, chunks = ItemRepository(conn), ChunkRepository(conn)
    embedder = build_embedder(settings)

    retriever = Retriever(chunks, embedder)
    llm = (
        OpenAILlm(settings.openai_api_key, settings.openai_chat_model)
        if settings.openai_api_key
        else None
    )

    pipeline = IngestPipeline(items=items, chunks=chunks, embedder=embedder, settings=settings)
    queue = IngestQueue(handler=pipeline.process, workers=settings.ingest_workers)
    await queue.start()
    await recover_pending(items, queue)

    app.state.settings = settings
    app.state.items = items
    app.state.chunks = chunks
    app.state.embedder = embedder
    app.state.queue = queue
    app.state.retriever = retriever
    app.state.answerer = Answerer(
        retriever=retriever, llm=llm, threshold=settings.abstain_threshold
    )
    log.info("startup_complete", db=settings.db_path, embed_model=embedder.model)
    try:
        yield
    finally:
        await queue.stop()
        await conn.close()
        log.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="AI Knowledge Inbox", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(items_router)
    app.include_router(query_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
