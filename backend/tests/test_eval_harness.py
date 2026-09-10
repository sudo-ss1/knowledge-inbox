import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
sys.path.insert(0, str(EVAL_DIR))

from run_eval import (
    Bm25,
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


def test_sweep_breaks_accuracy_ties_by_choosing_the_widest_margin():
    """Several candidates in a clean gap all score 1.0 accuracy; the widest-margin
    one (furthest from every observed score) should win, not merely the first
    or lowest one that reaches perfect accuracy."""
    rows = [
        {"answerable": True, "top_score": 0.8},
        {"answerable": True, "top_score": 0.7},
        {"answerable": False, "top_score": 0.2},
        {"answerable": False, "top_score": 0.1},
    ]

    threshold, accuracy = sweep_threshold(rows, [0.15, 0.3, 0.5, 0.7, 0.75])

    assert threshold == 0.5
    assert accuracy == 1.0


def test_bm25_ranks_the_obviously_matching_document_first():
    docs = {
        "cats": "cats are small domesticated felines that like to nap all day",
        "cars": "cars are motor vehicles with wheels and an engine",
        "boats": "boats float on water and are propelled by engines or sails",
    }
    bm25 = Bm25(docs)

    ranked = bm25.rank("tell me about domesticated felines that nap")

    assert ranked[0] == "cats"


def test_bm25_idf_downweights_a_term_common_to_every_document():
    """A term present in every document should contribute close to no ranking
    signal, while a term unique to one document should dominate. These four
    documents are built so a naive TF-only scorer (summing raw term
    frequency, ignoring IDF) would rank 'decoy' first: it repeats the
    everywhere-term 'common' five times against 'target's one occurrence of
    'common' plus one occurrence of 'rare', which appears in no other
    document. Real IDF weighting flips that -- 'rare' has df=1 against
    'common's df=4, so its high IDF should push 'target' to the top. Asserting
    BM25's actual order (not just that it differs from TF-only) is what
    confirms IDF is wired up, not merely present in the formula."""
    docs = {
        "target": "common rare",
        "decoy": "common common common common common",
        "filler_a": "common apple",
        "filler_b": "common banana",
    }
    bm25 = Bm25(docs)

    assert bm25.rank("common rare")[0] == "target"


def test_the_corpus_and_golden_set_are_consistent():
    corpus = load_corpus(EVAL_DIR / "corpus" / "corpus.json")
    golden = load_golden(EVAL_DIR / "golden.json")
    known_ids = {doc["id"] for doc in corpus}

    assert len(corpus) >= 18
    assert len(golden) >= 18
    assert sum(1 for q in golden if not q["answerable"]) >= 4

    for question in golden:
        for item_id in question["relevant_item_ids"]:
            assert item_id in known_ids, f"{question['id']} cites unknown doc {item_id}"
        if question["answerable"]:
            assert question["relevant_item_ids"], f"{question['id']} is answerable but has no label"
        else:
            assert question["relevant_item_ids"] == []
