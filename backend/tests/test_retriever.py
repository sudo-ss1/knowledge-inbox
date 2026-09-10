import numpy as np
import pytest

from app.errors import ApiError
from app.rag.chunker import Chunk
from app.rag.embedder import FakeEmbedder
from app.rag.retriever import Retriever
from app.store.db import connect
from app.store.repository import ChunkRepository, ItemRepository


@pytest.fixture
async def repos(tmp_path):
    conn = await connect(str(tmp_path / "retrieve.db"))
    yield ItemRepository(conn), ChunkRepository(conn)
    await conn.close()


async def _ready_item(items, chunks, embedder, *, title, texts, source_url=None):
    item = await items.create(
        type="url" if source_url else "note",
        source_url=source_url,
        title=title,
        raw_content=" ".join(texts),
    )
    vectors = await embedder.embed(texts)
    chunk_list = [
        Chunk(ordinal=i, text=text, token_count=len(text.split()))
        for i, text in enumerate(texts)
    ]
    await chunks.insert_many(
        item.id,
        chunk_list,
        vectors,
        embedder.model,
    )
    await items.mark_ready(item.id)
    return item


async def test_search_ranks_the_relevant_chunk_first(repos):
    items, chunks = repos
    embedder = FakeEmbedder(dim=256)
    await _ready_item(items, chunks, embedder, title="Bread", texts=["sourdough starter hydration"])
    await _ready_item(
        items, chunks, embedder, title="Kafka", texts=["consumer group rebalance coordinator"]
    )

    hits = await Retriever(chunks, embedder).search("kafka consumer rebalance", top_k=2)

    assert hits[0].title == "Kafka"
    assert hits[0].score > hits[1].score


async def test_search_returns_at_most_top_k(repos):
    items, chunks = repos
    embedder = FakeEmbedder(dim=64)
    texts = [f"chunk {i}" for i in range(10)]
    await _ready_item(items, chunks, embedder, title="Many", texts=texts)

    assert len(await Retriever(chunks, embedder).search("chunk", top_k=3)) == 3


async def test_search_over_an_empty_corpus_returns_nothing(repos):
    _, chunks = repos

    assert await Retriever(chunks, FakeEmbedder()).search("anything", top_k=5) == []


async def test_chunks_of_pending_items_are_invisible(repos):
    items, chunks = repos
    embedder = FakeEmbedder(dim=64)
    pending = await items.create(type="note", source_url=None, title="P", raw_content="hidden text")
    await chunks.insert_many(
        pending.id,
        [Chunk(0, "hidden text", 2)],
        await embedder.embed(["hidden text"]),
        embedder.model,
    )

    assert await Retriever(chunks, embedder).search("hidden", top_k=5) == []


async def test_hits_carry_the_metadata_needed_for_a_citation(repos):
    items, chunks = repos
    embedder = FakeEmbedder(dim=64)
    item = await _ready_item(
        items,
        chunks,
        embedder,
        title="Kafka Docs",
        texts=["rebalance protocol details"],
        source_url="https://kafka.test/docs",
    )

    hit = (await Retriever(chunks, embedder).search("rebalance", top_k=1))[0]

    assert hit.item_id == item.id
    assert hit.chunk_id.startswith("chk_")
    assert hit.title == "Kafka Docs"
    assert hit.source_url == "https://kafka.test/docs"
    assert hit.text == "rebalance protocol details"


async def test_a_dimension_mismatch_is_a_409_telling_the_user_to_reingest(repos):
    items, chunks = repos
    stored = FakeEmbedder(dim=32)
    await _ready_item(items, chunks, stored, title="Old", texts=["stored with the old model"])

    with pytest.raises(ApiError) as caught:
        await Retriever(chunks, FakeEmbedder(dim=64)).search("anything", top_k=1)

    assert caught.value.code == "embedding_dim_mismatch"
    assert caught.value.http_status == 409
    assert "re-ingest" in caught.value.message.lower()


async def test_genuinely_mixed_dimensions_raise_embedding_dim_mismatch_not_valueerror(repos):
    items, chunks = repos
    small = FakeEmbedder(dim=32, model="model-a")
    await _ready_item(items, chunks, small, title="Small", texts=["stored small"])
    big = FakeEmbedder(dim=64, model="model-b")
    await _ready_item(items, chunks, big, title="Big", texts=["stored big"])

    with pytest.raises(ApiError) as caught:
        await Retriever(chunks, big).search("anything", top_k=2)

    assert caught.value.code == "embedding_dim_mismatch"
    assert caught.value.http_status == 409


async def test_scores_are_cosine_similarities_in_range(repos):
    items, chunks = repos
    embedder = FakeEmbedder(dim=64)
    await _ready_item(items, chunks, embedder, title="T", texts=["alpha beta gamma"])

    hit = (await Retriever(chunks, embedder).search("alpha beta gamma", top_k=1))[0]

    assert 0.99 <= hit.score <= 1.01


async def test_search_vector_accepts_a_precomputed_vector(repos):
    items, chunks = repos
    embedder = FakeEmbedder(dim=64)
    await _ready_item(items, chunks, embedder, title="T", texts=["alpha beta"])
    retriever = Retriever(chunks, embedder)

    vector = await retriever.embed_question("alpha beta")
    hits = await retriever.search_vector(vector, top_k=1)

    assert hits[0].title == "T"
    assert np.isclose(np.linalg.norm(vector), 1.0)


async def test_mixed_embed_models_are_logged_as_a_warning(repos, caplog):
    items, chunks = repos
    embedder = FakeEmbedder(dim=64, model="model-a")
    await _ready_item(items, chunks, embedder, title="A", texts=["first"])
    other = FakeEmbedder(dim=64, model="model-b")
    await _ready_item(items, chunks, other, title="B", texts=["second"])

    with caplog.at_level("WARNING"):
        await Retriever(chunks, embedder).search("first", top_k=1)

    assert "mixed_embed_models" in caplog.text
