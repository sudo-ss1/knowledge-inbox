"""Sentence-packed windows.

Notes and articles have opposite shapes and one parameter set has to serve
both. Packing whole sentences means anything under `target_tokens` emits a
single untouched chunk, so a two-line note is never shredded, while long
extracted prose still gets overlapping windows that keep an answer-bearing
sentence off a boundary.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    token_count: int


@lru_cache(maxsize=1)
def _encoding() -> "tiktoken.Encoding":
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        sentences.extend(s.strip() for s in _SENTENCE_BOUNDARY.split(paragraph) if s.strip())
    return sentences


def _units(text: str, target_tokens: int) -> list[tuple[str, int]]:
    """Sentences, with any sentence larger than a whole window pre-split."""
    encoding = _encoding()
    units: list[tuple[str, int]] = []
    for sentence in split_sentences(text):
        tokens = encoding.encode(sentence)
        if len(tokens) <= target_tokens:
            units.append((sentence, len(tokens)))
            continue
        for start in range(0, len(tokens), target_tokens):
            piece = tokens[start : start + target_tokens]
            units.append((encoding.decode(piece).strip(), len(piece)))
    return units


def _overlap_tail(
    window: list[tuple[str, int]], overlap_tokens: int
) -> tuple[list[tuple[str, int]], int]:
    tail: list[tuple[str, int]] = []
    total = 0
    for sentence, tokens in reversed(window):
        if total + tokens > overlap_tokens:
            break
        tail.insert(0, (sentence, tokens))
        total += tokens
    return tail, total


def _emit(ordinal: int, window: list[tuple[str, int]], total: int) -> Chunk:
    return Chunk(ordinal=ordinal, text=" ".join(s for s, _ in window), token_count=total)


def chunk_text(text: str, target_tokens: int = 400, overlap_tokens: int = 60) -> list[Chunk]:
    units = _units(text, target_tokens)
    if not units:
        return []

    chunks: list[Chunk] = []
    window: list[tuple[str, int]] = []
    total = 0

    for sentence, tokens in units:
        if window and total + tokens > target_tokens:
            chunks.append(_emit(len(chunks), window, total))
            window, total = _overlap_tail(window, overlap_tokens)
            # Overlap must never push the next window over the target.
            if total + tokens > target_tokens:
                window, total = [], 0
        window.append((sentence, tokens))
        total += tokens

    if window:
        chunks.append(_emit(len(chunks), window, total))
    return chunks
