"""Measure retrieval and grounding against a fixed golden set.

Run from the backend virtualenv:  make eval
Needs OPENAI_API_KEY -- the corpus is pinned, but embedding it is a real call.
"""

import asyncio
import json
import math
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import Settings
from app.rag.answerer import Answerer, OpenAILlm
from app.rag.chunker import chunk_text
from app.rag.embedder import build_embedder
from app.rag.retriever import Retriever
from app.store.db import connect
from app.store.repository import ChunkRepository, ItemRepository

EVAL_DIR = Path(__file__).resolve().parent
THRESHOLD_CANDIDATES = [round(0.05 + 0.005 * step, 4) for step in range(111)]

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class Bm25:
    """Okapi BM25 over whole documents. A deliberately unintelligent baseline:
    if dense retrieval cannot beat it, the corpus is not exercising embeddings."""

    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75) -> None:
        self._k1, self._b = k1, b
        self._doc_tokens = {doc_id: _tokens(text) for doc_id, text in docs.items()}
        self._lengths = {doc_id: len(toks) for doc_id, toks in self._doc_tokens.items()}
        self._avg_len = sum(self._lengths.values()) / max(1, len(self._lengths))
        self._tf = {doc_id: Counter(toks) for doc_id, toks in self._doc_tokens.items()}
        self._df: Counter = Counter()
        for toks in self._doc_tokens.values():
            self._df.update(set(toks))
        self._n = len(self._doc_tokens)

    def rank(self, question: str) -> list[str]:
        """Document ids, best first."""
        scores: dict[str, float] = {}
        for doc_id in self._doc_tokens:
            score = 0.0
            for term in _tokens(question):
                freq = self._tf[doc_id].get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (self._n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                norm = freq + self._k1 * (
                    1 - self._b + self._b * self._lengths[doc_id] / self._avg_len
                )
                score += idf * (freq * (self._k1 + 1)) / norm
            scores[doc_id] = score
        return sorted(scores, key=lambda doc_id: -scores[doc_id])


def load_corpus(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())


def load_golden(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())


def recall_at_k(ranked_item_ids: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return 1.0 if relevant & set(ranked_item_ids[:k]) else 0.0


def reciprocal_rank(ranked_item_ids: list[str], relevant: set[str]) -> float:
    for position, item_id in enumerate(ranked_item_ids, start=1):
        if item_id in relevant:
            return 1.0 / position
    return 0.0


def sweep_threshold(rows: list[dict], candidates: list[float]) -> tuple[float, float]:
    """Pick the accuracy-maximizing cutoff, breaking ties by margin.

    When a clean gap separates answerable from unanswerable top scores, many
    candidates tie on accuracy. Preferring the one furthest from every observed
    score turns an arbitrary pick into a maximum-margin choice.
    """
    if not rows:
        return candidates[0], 0.0

    scored = []
    for threshold in candidates:
        correct = sum(
            1 for row in rows if (row["top_score"] >= threshold) == bool(row["answerable"])
        )
        margin = min(abs(row["top_score"] - threshold) for row in rows)
        scored.append((correct / len(rows), margin, threshold))

    accuracy, _, threshold = max(scored)
    return threshold, round(accuracy, 4)


async def _ingest_corpus(corpus, items, chunks, embedder, settings) -> dict[str, str]:
    """Returns a map of corpus doc id -> database item id."""
    mapping: dict[str, str] = {}
    for doc in corpus:
        item = await items.create(
            type=doc["type"],
            source_url=doc.get("source"),
            title=doc["title"],
            raw_content=doc["content"],
        )
        pieces = chunk_text(
            doc["content"],
            target_tokens=settings.chunk_target_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
        vectors = await embedder.embed([piece.text for piece in pieces])
        await chunks.insert_many(item.id, pieces, vectors, embedder.model)
        await items.mark_ready(item.id)
        mapping[doc["id"]] = item.id
        print(f"  indexed {doc['id']:<28} {len(pieces)} chunks")
    return mapping


async def main() -> None:
    settings = Settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required to run the eval.")

    corpus = load_corpus(EVAL_DIR / "corpus" / "corpus.json")
    golden = load_golden(EVAL_DIR / "golden.json")
    bm25 = Bm25({doc["id"]: f"{doc['title']} {doc['content']}" for doc in corpus})

    with tempfile.TemporaryDirectory() as workdir:
        conn = await connect(str(Path(workdir) / "eval.db"))
        items, chunks = ItemRepository(conn), ChunkRepository(conn)
        embedder = build_embedder(settings)

        print(f"Indexing {len(corpus)} documents with {embedder.model}")
        doc_to_item = await _ingest_corpus(corpus, items, chunks, embedder, settings)

        retriever = Retriever(chunks, embedder)
        answerer = Answerer(
            retriever=retriever,
            llm=OpenAILlm(settings.openai_api_key, settings.openai_chat_model),
            threshold=settings.abstain_threshold,
        )

        rows = []
        print(f"\nRunning {len(golden)} questions")
        for question in golden:
            try:
                relevant = {doc_to_item[doc_id] for doc_id in question["relevant_item_ids"]}
                hits = await retriever.search(question["question"], top_k=10)
                ranked = list(dict.fromkeys(hit.item_id for hit in hits))
                bm25_ranked = [doc_to_item[doc_id] for doc_id in bm25.rank(question["question"])]
                result = await answerer.answer(
                    question["question"], top_k=settings.retrieval_top_k
                )

                rows.append(
                    {
                        "id": question["id"],
                        "answerable": question["answerable"],
                        "top_score": round(float(hits[0].score) if hits else 0.0, 4),
                        "recall@5": recall_at_k(ranked, relevant, 5),
                        "recall@10": recall_at_k(ranked, relevant, 10),
                        "rr": reciprocal_rank(ranked, relevant),
                        "bm25_recall@5": recall_at_k(bm25_ranked, relevant, 5),
                        "bm25_rr": reciprocal_rank(bm25_ranked, relevant),
                        "abstained": result.abstained,
                        "citations": len(result.citations),
                        "markers_emitted": result.markers_emitted,
                        "markers_invented": result.markers_invented,
                        "abstain_reason": result.abstain_reason,
                    }
                )
                print(
                    f"  {question['id']}  top={rows[-1]['top_score']:.4f}"
                    f"  abstained={result.abstained}"
                )
            except KeyError:
                # A bad relevant_item_ids label (or a BM25-ranked doc id with no
                # matching item) is a data bug in the golden set, not a transient
                # API error -- let it surface as itself rather than being folded
                # into the "reporting what we have" partial-run path below.
                raise
            except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment below
                # A paid run that fails partway should still report what it already
                # bought, rather than aborting with a traceback and losing every row.
                print(f"  ! {question['id']} failed: {exc} -- reporting {len(rows)} rows so far")
                break

        await conn.close()

    _report(rows, settings, expected_questions=len(golden))


def _report(rows: list[dict], settings: Settings, expected_questions: int) -> None:
    if not rows:
        print("\nNo rows were collected -- nothing to report.")
        return

    if len(rows) != expected_questions:
        print(f"\n*** PARTIAL RUN -- {len(rows)} of {expected_questions} questions ***")

    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    llm_called = [row for row in rows if row["abstain_reason"] != "below_threshold"]

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    correct_abstentions = sum(1 for row in unanswerable if row["abstained"])
    correct_answers = sum(1 for row in answerable if not row["abstained"])
    best_threshold, best_accuracy = sweep_threshold(rows, THRESHOLD_CANDIDATES)

    print("\n== Retrieval: dense vs BM25 baseline (answerable questions only) ==")
    print("                  dense    bm25")
    print(
        f"  recall@5        {mean([row['recall@5'] for row in answerable]):.3f}"
        f"    {mean([row['bm25_recall@5'] for row in answerable]):.3f}"
    )
    print(
        f"  MRR             {mean([row['rr'] for row in answerable]):.3f}"
        f"    {mean([row['bm25_rr'] for row in answerable]):.3f}"
    )
    print(f"  recall@10 (dense only, near-vacuous at this corpus size)  "
          f"{mean([row['recall@10'] for row in answerable]):.3f}")

    emitted_total = sum(row["markers_emitted"] for row in llm_called)
    invented_total = sum(row["markers_invented"] for row in llm_called)
    invented_rate = round(invented_total / emitted_total, 4) if emitted_total else 0.0
    zero_citation_downgrades = sum(
        1 for row in rows if row["abstain_reason"] == "no_valid_citations"
    )

    print("\n== Grounding (measured against raw model output) ==")
    print(f"  markers emitted            {emitted_total}")
    print(f"  invented markers dropped   {invented_total}  (rate {invented_rate:.3f})")
    print(f"  answers downgraded to abstention for zero valid citations   "
          f"{zero_citation_downgrades}")

    print("\n== Abstention ==")
    print(f"  correct refusals   {correct_abstentions}/{len(unanswerable)}")
    print(f"  correct answers    {correct_answers}/{len(answerable)}")
    print(f"  accuracy           {(correct_abstentions + correct_answers) / len(rows):.3f}")

    print(f"\n== Threshold calibration (shipping {settings.abstain_threshold}) ==")
    print(f"  best threshold {best_threshold} at accuracy {best_accuracy}")
    if abs(best_threshold - settings.abstain_threshold) > 0.01:
        print(f"  -> consider setting ABSTAIN_THRESHOLD={best_threshold}")


if __name__ == "__main__":
    asyncio.run(main())
