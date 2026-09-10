import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
sys.path.insert(0, str(EVAL_DIR))

from run_eval import (
    load_corpus,
    load_golden,
    recall_at_k,
    reciprocal_rank,
    sweep_threshold,
)


def test_recall_counts_a_hit_inside_k():
    assert recall_at_k(["a", "b", "c"], {"c"}, 3) == 1.0


def test_recall_misses_a_hit_outside_k():
    assert recall_at_k(["a", "b", "c"], {"c"}, 2) == 0.0


def test_recall_is_zero_when_nothing_is_relevant():
    assert recall_at_k(["a"], set(), 1) == 0.0


def test_reciprocal_rank_uses_the_first_hit():
    assert reciprocal_rank(["a", "b", "c"], {"b"}) == 0.5


def test_reciprocal_rank_is_zero_on_a_total_miss():
    assert reciprocal_rank(["a", "b"], {"z"}) == 0.0


def test_sweep_picks_the_threshold_that_separates_best():
    rows = [
        {"answerable": True, "top_score": 0.60},
        {"answerable": True, "top_score": 0.55},
        {"answerable": False, "top_score": 0.10},
        {"answerable": False, "top_score": 0.15},
    ]

    threshold, accuracy = sweep_threshold(rows, [0.05, 0.30, 0.90])

    assert threshold == 0.30
    assert accuracy == 1.0


def test_the_corpus_and_golden_set_are_consistent():
    corpus = load_corpus(EVAL_DIR / "corpus" / "corpus.json")
    golden = load_golden(EVAL_DIR / "golden.json")
    known_ids = {doc["id"] for doc in corpus}

    assert len(corpus) >= 15
    assert len(golden) >= 15
    assert sum(1 for q in golden if not q["answerable"]) >= 3

    for question in golden:
        for item_id in question["relevant_item_ids"]:
            assert item_id in known_ids, f"{question['id']} cites unknown doc {item_id}"
        if question["answerable"]:
            assert question["relevant_item_ids"], f"{question['id']} is answerable but has no label"
        else:
            assert question["relevant_item_ids"] == []
