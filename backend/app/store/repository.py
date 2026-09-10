import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite
import numpy as np

from ..errors import ApiError
from ..rag.chunker import Chunk
from ..rag.embedder import to_blob

_ITEM_COLUMNS = """
  i.id, i.type, i.source_url, i.title, i.raw_content, i.status, i.error,
  i.created_at, i.updated_at,
  (SELECT COUNT(*) FROM chunks c WHERE c.item_id = i.id) AS chunk_count
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class Item:
    id: str
    type: str
    source_url: str | None
    title: str | None
    raw_content: str | None
    status: str
    error: str | None
    chunk_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ChunkRow:
    chunk_id: str
    item_id: str
    text: str
    title: str | None
    source_url: str | None
    embedding: bytes
    embed_model: str


def _to_item(row: aiosqlite.Row) -> Item:
    return Item(
        id=row["id"],
        type=row["type"],
        source_url=row["source_url"],
        title=row["title"],
        raw_content=row["raw_content"],
        status=row["status"],
        error=row["error"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _encode_cursor(item: Item) -> str:
    return f"{item.created_at}|{item.id}"


def _decode_cursor(cursor: str) -> tuple[str, str]:
    created_at, _, item_id = cursor.partition("|")
    if not created_at or not item_id:
        raise ApiError("bad_cursor", "That cursor is not one we issued.", 400)
    return created_at, item_id


class ItemRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(
        self, *, type: str, source_url: str | None, title: str | None, raw_content: str | None
    ) -> Item:
        item_id, now = new_id("itm"), _now()
        await self._conn.execute(
            """INSERT INTO items
               (id, type, source_url, title, raw_content, status, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?, ?)""",
            (item_id, type, source_url, title, raw_content, now, now),
        )
        await self._conn.commit()
        return await self.get(item_id)

    async def get(self, item_id: str) -> Item | None:
        async with self._conn.execute(
            f"SELECT {_ITEM_COLUMNS} FROM items i WHERE i.id = ?", (item_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return _to_item(row) if row else None

    async def list_page(
        self, *, status: str | None, limit: int, cursor: str | None
    ) -> tuple[list[Item], str | None]:
        where, params = [], []
        if status:
            where.append("i.status = ?")
            params.append(status)
        if cursor:
            created_at, item_id = _decode_cursor(cursor)
            where.append("(i.created_at, i.id) < (?, ?)")
            params.extend([created_at, item_id])

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit + 1)
        async with self._conn.execute(
            f"""SELECT {_ITEM_COLUMNS} FROM items i {clause}
                ORDER BY i.created_at DESC, i.id DESC LIMIT ?""",
            tuple(params),
        ) as db_cursor:
            rows = await db_cursor.fetchall()

        items = [_to_item(row) for row in rows]
        if len(items) > limit:
            return items[:limit], _encode_cursor(items[limit - 1])
        return items, None

    async def set_content(self, item_id: str, *, title: str | None, raw_content: str) -> None:
        await self._conn.execute(
            "UPDATE items SET title = ?, raw_content = ?, updated_at = ? WHERE id = ?",
            (title, raw_content, _now(), item_id),
        )
        await self._conn.commit()

    async def mark_ready(self, item_id: str) -> None:
        await self._conn.execute(
            "UPDATE items SET status = 'ready', error = NULL, updated_at = ? WHERE id = ?",
            (_now(), item_id),
        )
        await self._conn.commit()

    async def mark_failed(self, item_id: str, error: str) -> None:
        await self._conn.execute(
            "UPDATE items SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (error, _now(), item_id),
        )
        await self._conn.commit()

    async def pending_ids(self) -> list[str]:
        async with self._conn.execute(
            "SELECT id FROM items WHERE status = 'pending' ORDER BY created_at ASC"
        ) as cursor:
            return [row["id"] for row in await cursor.fetchall()]


class ChunkRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def insert_many(
        self,
        item_id: str,
        chunks: list[Chunk],
        vectors: list[np.ndarray],
        embed_model: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ApiError("chunk_vector_mismatch", "Chunk and vector counts disagree.", 500)
        rows = [
            (
                new_id("chk"),
                item_id,
                chunk.ordinal,
                chunk.text,
                chunk.token_count,
                to_blob(vector),
                embed_model,
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        await self._conn.executemany(
            """INSERT INTO chunks (id, item_id, ordinal, text, token_count, embedding, embed_model)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self._conn.commit()

    async def load_ready(self) -> list[ChunkRow]:
        async with self._conn.execute(
            """SELECT c.id, c.item_id, c.text, c.embedding, c.embed_model, i.title, i.source_url
               FROM chunks c JOIN items i ON i.id = c.item_id
               WHERE i.status = 'ready'
               ORDER BY c.item_id, c.ordinal"""
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            ChunkRow(
                chunk_id=row["id"],
                item_id=row["item_id"],
                text=row["text"],
                title=row["title"],
                source_url=row["source_url"],
                embedding=row["embedding"],
                embed_model=row["embed_model"],
            )
            for row in rows
        ]

    async def count_for(self, item_id: str) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE item_id = ?", (item_id,)
        ) as cursor:
            return (await cursor.fetchone())["n"]
