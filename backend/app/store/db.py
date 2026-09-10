from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id           TEXT PRIMARY KEY,
  type         TEXT NOT NULL CHECK (type IN ('note', 'url')),
  source_url   TEXT,
  title        TEXT,
  raw_content  TEXT,
  status       TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
  error        TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id           TEXT PRIMARY KEY,
  item_id      TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  ordinal      INTEGER NOT NULL,
  text         TEXT NOT NULL,
  token_count  INTEGER NOT NULL,
  embedding    BLOB NOT NULL,
  embed_model  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_item ON chunks(item_id);
CREATE INDEX IF NOT EXISTS idx_items_status_created ON items(status, created_at DESC);
"""


async def connect(db_path: str) -> aiosqlite.Connection:
    Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn
