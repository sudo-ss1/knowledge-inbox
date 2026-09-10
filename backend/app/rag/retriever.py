"""Exact brute-force cosine search.

At the scale this app occupies -- a few thousand chunks -- a full scan is
single-digit milliseconds and an ANN index would add tuning surface for no
measurable gain. The cost is honest: O(N) per query in both time and bytes
read. This interface is deliberately narrow so swapping in pgvector or Qdrant
is a one-file change.
"""

from dataclasses import dataclass

import numpy as np

from ..errors import ApiError
from ..logging import get_logger
from ..rag.embedder import Embedder, from_blob
from ..store.repository import ChunkRepository

log = get_logger(__name__)


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    item_id: str
    text: str
    title: str | None
    source_url: str | None
    score: float


class Retriever:
    def __init__(self, chunks: ChunkRepository, embedder: Embedder) -> None:
        self._chunks = chunks
        self._embedder = embedder

    async def embed_question(self, question: str) -> np.ndarray:
        vectors = await self._embedder.embed([question])
        return vectors[0]

    async def search(self, question: str, top_k: int) -> list[Hit]:
        return await self.search_vector(await self.embed_question(question), top_k)

    async def search_vector(self, vector: np.ndarray, top_k: int) -> list[Hit]:
        rows = await self._chunks.load_ready()
        if not rows:
            return []

        models = {row.embed_model for row in rows}
        if len(models) > 1:
            log.warning("mixed_embed_models", models=sorted(models))

        stored = [from_blob(row.embedding) for row in rows]
        dims = {v.shape[0] for v in stored}
        if len(dims) > 1:
            # Rows were embedded by more than one model/dimension. Stacking these
            # into one matrix would raise a raw ValueError, so surface the same
            # user-facing error the single-dimension-vs-query mismatch below does --
            # to a user both are "re-ingest, your embeddings don't match".
            raise ApiError(
                "embedding_dim_mismatch",
                "Stored embeddings were built with a different model. "
                "Re-ingest your items or restore the previous OPENAI_EMBED_MODEL.",
                409,
            )

        matrix = np.vstack(stored)
        if matrix.shape[1] != vector.shape[0]:
            raise ApiError(
                "embedding_dim_mismatch",
                "Stored embeddings were built with a different model. "
                "Re-ingest your items or restore the previous OPENAI_EMBED_MODEL.",
                409,
            )

        scores = matrix @ vector
        count = min(top_k, len(rows))
        top = np.argpartition(-scores, count - 1)[:count]
        top = top[np.argsort(-scores[top])]

        return [
            Hit(
                chunk_id=rows[index].chunk_id,
                item_id=rows[index].item_id,
                text=rows[index].text,
                title=rows[index].title,
                source_url=rows[index].source_url,
                score=float(scores[index]),
            )
            for index in top
        ]
