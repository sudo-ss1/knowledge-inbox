import itertools

from app.rag.chunker import chunk_text, count_tokens, split_sentences

SENTENCE = "Consumer group membership changed and the coordinator triggered a rebalance. "

# Distinct sentences, so a set intersection actually means shared content.
DISTINCT_SENTENCES = [
    f"Idea {index} covers a separate topic worth remembering here." for index in range(80)
]
DISTINCT_TEXT = " ".join(DISTINCT_SENTENCES)


def test_a_short_note_is_never_split():
    note = "Kafka rebalances when group membership changes. Remember this."

    chunks = chunk_text(note, target_tokens=400, overlap_tokens=60)

    assert len(chunks) == 1
    assert chunks[0].text == note
    assert chunks[0].ordinal == 0


def test_empty_and_whitespace_input_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_long_text_splits_into_multiple_ordered_chunks():
    chunks = chunk_text(SENTENCE * 120, target_tokens=100, overlap_tokens=20)

    assert len(chunks) > 1
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_no_chunk_exceeds_the_target():
    chunks = chunk_text(SENTENCE * 120, target_tokens=100, overlap_tokens=20)

    assert all(c.token_count <= 100 for c in chunks)


def test_chunks_never_break_mid_sentence():
    text = SENTENCE * 60
    chunks = chunk_text(text, target_tokens=100, overlap_tokens=20)

    for chunk in chunks:
        assert chunk.text.rstrip().endswith(".")
        assert chunk.text.lstrip().startswith("Consumer")


def test_consecutive_chunks_overlap_at_a_contiguous_seam():
    chunks = chunk_text(DISTINCT_TEXT, target_tokens=100, overlap_tokens=40)

    first = split_sentences(chunks[0].text)
    second = split_sentences(chunks[1].text)
    shared = len(set(first) & set(second))

    assert shared > 0
    # The shared sentences must be the tail of one chunk and the head of the next,
    # not merely present in both.
    assert first[-shared:] == second[:shared]


def test_zero_overlap_shares_no_sentences():
    """Sensitivity check: proves the overlap tests above can actually fail."""
    chunks = chunk_text(DISTINCT_TEXT, target_tokens=100, overlap_tokens=0)

    for earlier, later in itertools.pairwise(chunks):
        assert not set(split_sentences(earlier.text)) & set(split_sentences(later.text))


def test_overlap_is_bounded_by_the_setting():
    chunks = chunk_text(DISTINCT_TEXT, target_tokens=100, overlap_tokens=40)

    first = split_sentences(chunks[0].text)
    second = split_sentences(chunks[1].text)
    shared = len(set(first) & set(second))

    assert sum(count_tokens(sentence) for sentence in second[:shared]) <= 40


def test_a_single_oversized_sentence_is_hard_split():
    monster = "word " * 500

    chunks = chunk_text(monster, target_tokens=100, overlap_tokens=20)

    assert len(chunks) > 1
    assert all(c.token_count <= 100 for c in chunks)


def test_paragraph_breaks_do_not_produce_empty_chunks():
    chunks = chunk_text("First idea.\n\n\n\nSecond idea.", target_tokens=400, overlap_tokens=60)

    assert len(chunks) == 1
    assert chunks[0].text == "First idea. Second idea."


def test_split_sentences_handles_abbreviation_free_prose():
    assert split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]
