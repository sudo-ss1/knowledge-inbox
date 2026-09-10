"""Measure retrieval and grounding against a fixed golden set.

Run from the backend virtualenv:  make eval
Needs OPENAI_API_KEY -- the corpus is pinned, but embedding it is a real call.
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.rag.answerer import Answerer, OpenAILlm  # noqa: E402
from app.rag.chunker import chunk_text  # noqa: E402
from app.rag.embedder import build_embedder  # noqa: E402
from app.rag.retriever import Retriever  # noqa: E402
from app.store.db import connect  # noqa: E402
from app.store.repository import ChunkRepository, ItemRepository  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
THRESHOLD_CANDIDATES = [round(0.05 + 0.025 * step, 4) for step in range(23)]


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
            relevant = {doc_to_item[doc_id] for doc_id in question["relevant_item_ids"]}
            hits = await retriever.search(question["question"], top_k=10)
            ranked = list(dict.fromkeys(hit.item_id for hit in hits))
            result = await answerer.answer(question["question"], top_k=settings.retrieval_top_k)

            markers_valid = all(
                1 <= citation.marker <= settings.retrieval_top_k for citation in result.citations
            )
            rows.append(
                {
                    "id": question["id"],
                    "answerable": question["answerable"],
                    "top_score": round(float(hits[0].score) if hits else 0.0, 4),
                    "recall@5": recall_at_k(ranked, relevant, 5),
                    "recall@10": recall_at_k(ranked, relevant, 10),
                    "rr": reciprocal_rank(ranked, relevant),
                    "abstained": result.abstained,
                    "citations": len(result.citations),
                    "citations_valid": markers_valid,
                }
            )
            print(f"  {question['id']}  top={rows[-1]['top_score']:.3f}  abstained={result.abstained}")

        await conn.close()

    _report(rows, settings)


def _report(rows: list[dict], settings: Settings) -> None:
    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    answered = [row for row in rows if not row["abstained"]]

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    correct_abstentions = sum(1 for row in unanswerable if row["abstained"])
    correct_answers = sum(1 for row in answerable if not row["abstained"])
    best_threshold, best_accuracy = sweep_threshold(rows, THRESHOLD_CANDIDATES)

    print("\n== Retrieval (answerable questions only) ==")
    print(f"  recall@5   {mean([row['recall@5'] for row in answerable]):.3f}")
    print(f"  recall@10  {mean([row['recall@10'] for row in answerable]):.3f}")
    print(f"  MRR        {mean([row['rr'] for row in answerable]):.3f}")

    print("\n== Grounding ==")
    print(
        f"  citation validity  "
        f"{mean([1.0 if row['citations_valid'] else 0.0 for row in answered]):.3f}"
    )
    print(f"  answers with >=1 citation  {sum(1 for row in answered if row['citations'])}/{len(answered)}")

    print("\n== Abstention ==")
    print(f"  correct refusals   {correct_abstentions}/{len(unanswerable)}")
    print(f"  correct answers    {correct_answers}/{len(answerable)}")
    print(f"  accuracy           {(correct_abstentions + correct_answers) / len(rows):.3f}")

    print(f"\n== Threshold calibration (shipping {settings.abstain_threshold}) ==")
    print(f"  best threshold {best_threshold} at accuracy {best_accuracy}")
    if abs(best_threshold - settings.abstain_threshold) > 0.02:
        print(f"  -> consider setting ABSTAIN_THRESHOLD={best_threshold}")


if __name__ == "__main__":
    asyncio.run(main())
