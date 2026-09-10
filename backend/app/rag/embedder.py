import hashlib
import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from ..config import Settings

_WORD = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    async def embed(self, texts: list[str]) -> list[np.ndarray]: ...


def normalize(vector: np.ndarray) -> np.ndarray:
    """Unit-length so cosine similarity is a plain dot product later."""
    array = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        return array
    return (array / norm).astype(np.float32)


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


class OpenAIEmbedder:
    """Batches to keep a bulk ingest inside one request per 64 chunks."""

    def __init__(self, api_key: str, model: str, batch_size: int = 64) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._batch_size = batch_size

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            response = await self._client.embeddings.create(model=self._model, input=batch)
            vectors.extend(
                normalize(np.asarray(row.embedding, dtype=np.float32)) for row in response.data
            )
        return vectors


class FakeEmbedder:
    """Hashed bag-of-words vectors for tests.

    Uses md5 rather than hash() so vectors are stable across processes
    regardless of PYTHONHASHSEED.
    """

    def __init__(self, dim: int = 64, model: str = "fake-embed") -> None:
        self._dim = dim
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> np.ndarray:
        vector = np.zeros(self._dim, dtype=np.float32)
        for word in _WORD.findall(text.lower()):
            digest = hashlib.md5(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self._dim] += 1.0
        return normalize(vector)


class UnavailableEmbedder:
    """Stands in when no API key is configured, so failures are explicit."""

    @property
    def model(self) -> str:
        return "unavailable"

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        from ..errors import ApiError

        raise ApiError(
            "embedder_unavailable",
            "Embeddings are not configured. Set OPENAI_API_KEY and restart.",
            503,
        )


def build_embedder(settings: "Settings") -> Embedder:
    if not settings.openai_api_key:
        return UnavailableEmbedder()
    return OpenAIEmbedder(settings.openai_api_key, settings.openai_embed_model)
