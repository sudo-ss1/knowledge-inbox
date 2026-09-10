"""Grounded answering.

The important property is not the prompt, it is what happens after the model
replies: any citation marker the model invents is dropped, and an answer left
with no valid citation is downgraded to an abstention. An uncited answer over
retrieved context is ungrounded by construction, and a confidently wrong
answer costs the user more than "I don't know".
"""

import re
import time
from dataclasses import dataclass
from typing import Protocol

from ..logging import get_logger
from .retriever import Hit

log = get_logger(__name__)

ABSTENTION_MESSAGE = "I don't have anything saved that answers that."

SYSTEM_PROMPT = """You answer questions using only the numbered context passages provided.

Rules:
- Use only facts stated in the context. Never add outside knowledge.
- Cite the passage number in square brackets after each claim, like [1].
- If the context does not answer the question, reply with exactly this sentence \
and nothing else: I don't have anything saved that answers that.
- Be concise. Three sentences at most."""

_MARKER = re.compile(r"\[(\d+)\]")
SNIPPET_CHARS = 300


class LlmClient(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


class OpenAILlm:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(self, system: str, user: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (response.choices[0].message.content or "").strip()


class FakeLlm:
    """Returns a scripted answer. Used by every test, so none of them need a key."""

    def __init__(self, scripted: str) -> None:
        self._scripted = scripted

    async def complete(self, system: str, user: str) -> str:
        return self._scripted


@dataclass(frozen=True)
class Citation:
    marker: int
    chunk_id: str
    item_id: str
    title: str | None
    source_url: str | None
    snippet: str
    score: float


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    citations: list[Citation]
    abstained: bool
    timings_ms: dict[str, float]
    markers_emitted: int = 0
    markers_invented: int = 0
    abstain_reason: str | None = None


def build_prompt(question: str, hits: list[Hit]) -> str:
    blocks = []
    for number, hit in enumerate(hits, start=1):
        label = hit.title or hit.source_url or hit.item_id
        blocks.append(f"[{number}] {label}\n{hit.text}")
    return "Context:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"


def validate_citations(answer: str, hits: list[Hit]) -> tuple[str, list[Citation]]:
    """Drop invented markers, renumber the survivors, and return their sources."""
    kept: list[int] = []
    for raw in _MARKER.findall(answer):
        number = int(raw)
        if 1 <= number <= len(hits) and number not in kept:
            kept.append(number)

    if not kept:
        return answer.strip(), []

    remap = {old: new for new, old in enumerate(sorted(kept), start=1)}

    def replace(match: re.Match) -> str:
        number = int(match.group(1))
        return f"[{remap[number]}]" if number in remap else ""

    cleaned = _MARKER.sub(replace, answer)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

    citations = [
        Citation(
            marker=remap[old],
            chunk_id=hits[old - 1].chunk_id,
            item_id=hits[old - 1].item_id,
            title=hits[old - 1].title,
            source_url=hits[old - 1].source_url,
            snippet=hits[old - 1].text[:SNIPPET_CHARS],
            score=round(hits[old - 1].score, 4),
        )
        for old in sorted(kept)
    ]
    return cleaned, citations


def _looks_like_a_refusal(answer: str) -> bool:
    normalized = answer.strip().rstrip(".").casefold()
    return normalized == ABSTENTION_MESSAGE.rstrip(".").casefold()


class Answerer:
    def __init__(self, *, retriever, llm: LlmClient | None, threshold: float) -> None:
        self._retriever = retriever
        self._llm = llm
        self._threshold = threshold

    async def answer(self, question: str, top_k: int) -> AnswerResult:
        timings: dict[str, float] = {}

        started = time.perf_counter()
        vector = await self._retriever.embed_question(question)
        timings["embed"] = _elapsed_ms(started)

        started = time.perf_counter()
        hits = await self._retriever.search_vector(vector, top_k)
        timings["retrieve"] = _elapsed_ms(started)

        top_score = hits[0].score if hits else 0.0
        if not hits or top_score < self._threshold:
            timings["llm"] = 0.0
            log.info(
                "query_answered",
                abstained=True,
                reason="below_threshold",
                top_score=round(top_score, 4),
                hits=len(hits),
            )
            return AnswerResult(
                ABSTENTION_MESSAGE, [], True, timings, abstain_reason="below_threshold"
            )

        started = time.perf_counter()
        raw = await self._llm.complete(SYSTEM_PROMPT, build_prompt(question, hits))
        timings["llm"] = _elapsed_ms(started)

        emitted = [int(marker) for marker in _MARKER.findall(raw)]
        invented = [number for number in emitted if not (1 <= number <= len(hits))]

        if _looks_like_a_refusal(raw):
            log.info(
                "query_answered",
                abstained=True,
                reason="model_declined",
                top_score=round(top_score, 4),
            )
            return AnswerResult(
                ABSTENTION_MESSAGE,
                [],
                True,
                timings,
                markers_emitted=len(emitted),
                markers_invented=len(invented),
                abstain_reason="model_declined",
            )

        cleaned, citations = validate_citations(raw, hits)
        if not citations:
            log.warning(
                "query_answered",
                abstained=True,
                reason="no_valid_citations",
                top_score=round(top_score, 4),
            )
            return AnswerResult(
                ABSTENTION_MESSAGE,
                [],
                True,
                timings,
                markers_emitted=len(emitted),
                markers_invented=len(invented),
                abstain_reason="no_valid_citations",
            )

        log.info(
            "query_answered",
            abstained=False,
            top_score=round(top_score, 4),
            citations=len(citations),
            **{f"t_{key}": value for key, value in timings.items()},
        )
        return AnswerResult(
            cleaned,
            citations,
            False,
            timings,
            markers_emitted=len(emitted),
            markers_invented=len(invented),
            abstain_reason=None,
        )


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
