import numpy as np
import pytest

from app.rag.chunker import Chunk
from app.store.db import connect
from app.store.repository import ChunkRepository, ItemRepository


@pytest.fixture
async def conn(tmp_path):
    connection = await connect(str(tmp_path / "test.db"))
    yield connection
    await connection.close()


async def test_create_assigns_prefixed_id_and_pending_status(conn):
    items = ItemRepository(conn)
    item = await items.create(type="note", source_url=None, title="Hi", raw_content="Hello there")

    assert item.id.startswith("itm_")
    assert len(item.id) == 16
    assert item.status == "pending"
    assert item.created_at.endswith("Z")


async def test_get_returns_none_for_unknown_id(conn):
    assert await ItemRepository(conn).get("itm_nope") is None


async def test_mark_failed_stores_the_reason(conn):
    items = ItemRepository(conn)
    item = await items.create(type="url", source_url="https://x.test", title=None, raw_content=None)

    await items.mark_failed(item.id, "Upstream returned HTTP 500.")
    reloaded = await items.get(item.id)

    assert reloaded.status == "failed"
    assert reloaded.error == "Upstream returned HTTP 500."


async def test_list_page_is_newest_first_and_keyset_paginated(conn):
    items = ItemRepository(conn)
    created = [
        await items.create(type="note", source_url=None, title=f"n{i}", raw_content=f"body {i}")
        for i in range(5)
    ]

    first, cursor = await items.list_page(status=None, limit=2, cursor=None)
    assert [i.id for i in first] == [created[4].id, created[3].id]
    assert cursor is not None

    second, _ = await items.list_page(status=None, limit=2, cursor=cursor)
    assert [i.id for i in second] == [created[2].id, created[1].id]


async def test_list_page_filters_by_status(conn):
    items = ItemRepository(conn)
    a = await items.create(type="note", source_url=None, title="a", raw_content="a")
    await items.create(type="note", source_url=None, title="b", raw_content="b")
    await items.mark_ready(a.id)

    ready, _ = await items.list_page(status="ready", limit=10, cursor=None)
    assert [i.id for i in ready] == [a.id]


async def test_chunk_count_is_reported_on_the_item(conn):
    items, chunks = ItemRepository(conn), ChunkRepository(conn)
    item = await items.create(type="note", source_url=None, title="t", raw_content="body")

    await chunks.insert_many(
        item.id,
        [Chunk(ordinal=0, text="body", token_count=1)],
        [np.array([1.0, 0.0], dtype=np.float32)],
        "fake-embed",
    )

    assert (await items.get(item.id)).chunk_count == 1


async def test_load_ready_excludes_chunks_of_unready_items(conn):
    items, chunks = ItemRepository(conn), ChunkRepository(conn)
    ready_item = await items.create(type="note", source_url=None, title="r", raw_content="r")
    pending_item = await items.create(type="note", source_url=None, title="p", raw_content="p")
    vector = [np.array([1.0, 0.0], dtype=np.float32)]

    await chunks.insert_many(ready_item.id, [Chunk(0, "r", 1)], vector, "fake-embed")
    await chunks.insert_many(pending_item.id, [Chunk(0, "p", 1)], vector, "fake-embed")
    await items.mark_ready(ready_item.id)

    rows = await chunks.load_ready()
    assert [row.item_id for row in rows] == [ready_item.id]
    assert np.frombuffer(rows[0].embedding, dtype=np.float32).tolist() == [1.0, 0.0]


async def test_pending_ids_supports_startup_recovery(conn):
    items = ItemRepository(conn)
    stuck = await items.create(type="note", source_url=None, title="s", raw_content="s")
    done = await items.create(type="note", source_url=None, title="d", raw_content="d")
    await items.mark_ready(done.id)

    assert await items.pending_ids() == [stuck.id]


async def test_reinserting_chunks_for_an_item_replaces_rather_than_duplicates(conn):
    items, chunks = ItemRepository(conn), ChunkRepository(conn)
    item = await items.create(type="note", source_url=None, title="t", raw_content="body")
    vector = [np.array([1.0, 0.0], dtype=np.float32)]

    await chunks.insert_many(
        item.id, [Chunk(0, "first pass", 2)], vector, "fake-embed"
    )
    await chunks.insert_many(
        item.id,
        [Chunk(0, "second pass a", 3), Chunk(1, "second pass b", 3)],
        vector * 2,
        "fake-embed",
    )

    assert await chunks.count_for(item.id) == 2
    await items.mark_ready(item.id)  # load_ready only shows chunks of ready items
    rows = await chunks.load_ready()
    texts = {row.text for row in rows}
    assert texts == {"second pass a", "second pass b"}
    assert "first pass" not in texts


async def test_deleting_an_item_cascades_to_its_chunks(conn):
    items, chunks = ItemRepository(conn), ChunkRepository(conn)
    item = await items.create(type="note", source_url=None, title="t", raw_content="b")
    await chunks.insert_many(
        item.id, [Chunk(0, "b", 1)], [np.array([1.0], dtype=np.float32)], "fake-embed"
    )

    await conn.execute("DELETE FROM items WHERE id = ?", (item.id,))
    await conn.commit()

    assert await chunks.count_for(item.id) == 0
