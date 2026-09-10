from app.rag.answerer import (
    ABSTENTION_MESSAGE,
    Answerer,
    FakeLlm,
    build_prompt,
    validate_citations,
)
from app.rag.retriever import Hit


def hit(chunk_id: str, text: str, title: str) -> Hit:
    return Hit(
        chunk_id=chunk_id,
        item_id=f"itm_{chunk_id}",
        text=text,
        title=title,
        source_url=None,
        score=0.7,
    )


HITS = [hit("a", "Rebalance fires on membership change.", "Kafka"), hit("b", "WAL mode.", "SQLite")]


class StubRetriever:
    def __init__(self, hits, top_score=0.7):
        self._hits = hits
        self._top_score = top_score

    async def embed_question(self, question):
        return None

    async def search_vector(self, vector, top_k):
        return self._hits[:top_k]


def test_prompt_numbers_every_passage_and_ends_with_the_question():
    prompt = build_prompt("why rebalance?", HITS)

    assert "[1] Kafka" in prompt
    assert "[2] SQLite" in prompt
    assert prompt.rstrip().endswith("Question: why rebalance?")


def test_valid_markers_are_kept_and_mapped_to_sources():
    answer, citations = validate_citations("Membership changed [1].", HITS)

    assert answer == "Membership changed [1]."
    assert [c.marker for c in citations] == [1]
    assert citations[0].chunk_id == "a"


def test_out_of_range_markers_are_dropped():
    answer, citations = validate_citations("Claim [1] and invention [7].", HITS)

    assert "[7]" not in answer
    assert [c.marker for c in citations] == [1]


def test_surviving_markers_are_renumbered_contiguously():
    answer, citations = validate_citations("Only the second one matters [2].", HITS)

    assert "[1]" in answer
    assert "[2]" not in answer
    assert [c.marker for c in citations] == [1]
    assert citations[0].chunk_id == "b"


def test_repeated_markers_produce_one_source():
    _, citations = validate_citations("First [1], again [1].", HITS)

    assert [c.marker for c in citations] == [1]


def test_an_answer_with_no_markers_yields_no_citations():
    answer, citations = validate_citations("A confident claim with no source.", HITS)

    assert citations == []
    assert answer == "A confident claim with no source."


def test_citation_snippets_are_truncated():
    long_hit = hit("c", "x" * 900, "Long")

    _, citations = validate_citations("Cited [1].", [long_hit])

    assert len(citations[0].snippet) <= 300


async def test_a_grounded_answer_comes_back_with_its_sources():
    answerer = Answerer(
        retriever=StubRetriever(HITS), llm=FakeLlm("Membership changed [1]."), threshold=0.2
    )

    result = await answerer.answer("why rebalance?", top_k=2)

    assert result.abstained is False
    assert result.answer == "Membership changed [1]."
    assert [c.chunk_id for c in result.citations] == ["a"]


async def test_a_weak_top_score_abstains_without_calling_the_llm():
    class ExplodingLlm:
        async def complete(self, system, user):
            raise AssertionError("the LLM must not be called below threshold")

    weak = [Hit("a", "itm_a", "text", "T", None, 0.05)]
    answerer = Answerer(retriever=StubRetriever(weak), llm=ExplodingLlm(), threshold=0.25)

    result = await answerer.answer("unrelated question", top_k=5)

    assert result.abstained is True
    assert result.answer == ABSTENTION_MESSAGE
    assert result.citations == []


async def test_an_empty_corpus_abstains():
    answerer = Answerer(retriever=StubRetriever([]), llm=FakeLlm("anything"), threshold=0.2)

    result = await answerer.answer("anything", top_k=5)

    assert result.abstained is True


async def test_an_answer_with_zero_valid_citations_is_downgraded_to_an_abstention():
    """An uncited answer over retrieved context is ungrounded by construction."""
    answerer = Answerer(
        retriever=StubRetriever(HITS),
        llm=FakeLlm("Kafka rebalances because of Zookeeper magic."),
        threshold=0.2,
    )

    result = await answerer.answer("why rebalance?", top_k=2)

    assert result.abstained is True
    assert result.answer == ABSTENTION_MESSAGE


async def test_an_answer_whose_only_citation_is_invented_is_downgraded():
    answerer = Answerer(
        retriever=StubRetriever(HITS), llm=FakeLlm("It happens because of [9]."), threshold=0.2
    )

    result = await answerer.answer("why?", top_k=2)

    assert result.abstained is True


async def test_the_model_declining_is_reported_as_an_abstention():
    answerer = Answerer(
        retriever=StubRetriever(HITS), llm=FakeLlm(ABSTENTION_MESSAGE), threshold=0.2
    )

    result = await answerer.answer("something else", top_k=2)

    assert result.abstained is True
    assert result.citations == []


async def test_a_grounded_single_citation_reports_emitted_and_invented_counts():
    answerer = Answerer(
        retriever=StubRetriever(HITS), llm=FakeLlm("Membership changed [1]."), threshold=0.2
    )

    result = await answerer.answer("why rebalance?", top_k=2)

    assert result.markers_emitted == 1
    assert result.markers_invented == 0
    assert result.abstain_reason is None


async def test_one_invented_marker_among_two_emitted_is_counted_as_invented():
    answerer = Answerer(
        retriever=StubRetriever(HITS),
        llm=FakeLlm("Claim [1] and invention [7]."),
        threshold=0.2,
    )

    result = await answerer.answer("why rebalance?", top_k=2)

    assert result.markers_emitted == 2
    assert result.markers_invented == 1


async def test_an_answer_citing_only_an_invented_marker_reports_no_valid_citations():
    answerer = Answerer(
        retriever=StubRetriever(HITS), llm=FakeLlm("It happens because of [9]."), threshold=0.2
    )

    result = await answerer.answer("why?", top_k=2)

    assert result.markers_invented == 1
    assert result.abstain_reason == "no_valid_citations"


async def test_a_below_threshold_abstention_reports_its_reason():
    weak = [Hit("a", "itm_a", "text", "T", None, 0.05)]
    answerer = Answerer(retriever=StubRetriever(weak), llm=FakeLlm("anything"), threshold=0.25)

    result = await answerer.answer("unrelated question", top_k=5)

    assert result.abstain_reason == "below_threshold"


async def test_timings_report_the_embed_retrieve_and_llm_split():
    answerer = Answerer(
        retriever=StubRetriever(HITS), llm=FakeLlm("Grounded [1]."), threshold=0.2
    )

    result = await answerer.answer("why?", top_k=2)

    assert set(result.timings_ms) == {"embed", "retrieve", "llm"}
    assert all(value >= 0 for value in result.timings_ms.values())
