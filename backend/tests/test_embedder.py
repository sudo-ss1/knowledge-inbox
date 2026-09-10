import numpy as np

from app.rag.embedder import FakeEmbedder, from_blob, normalize, to_blob


async def test_fake_embedder_returns_one_unit_vector_per_text():
    embedder = FakeEmbedder(dim=32)

    vectors = await embedder.embed(["kafka rebalance", "sqlite wal"])

    assert len(vectors) == 2
    for vector in vectors:
        assert vector.shape == (32,)
        assert vector.dtype == np.float32
        assert np.isclose(np.linalg.norm(vector), 1.0)


async def test_fake_embedder_is_deterministic_across_instances():
    first = await FakeEmbedder(dim=32).embed(["same text"])
    second = await FakeEmbedder(dim=32).embed(["same text"])

    assert np.array_equal(first[0], second[0])


async def test_similar_text_scores_higher_than_unrelated_text():
    embedder = FakeEmbedder(dim=256)

    query, near, far = await embedder.embed(
        ["kafka consumer rebalance", "kafka rebalance of a consumer group", "sourdough baking"]
    )

    assert float(query @ near) > float(query @ far)


async def test_empty_text_does_not_divide_by_zero():
    vectors = await FakeEmbedder(dim=8).embed([""])

    assert np.all(vectors[0] == 0.0)


def test_normalize_leaves_a_zero_vector_alone():
    assert np.all(normalize(np.zeros(4, dtype=np.float32)) == 0.0)


def test_blob_round_trip_preserves_the_vector():
    vector = normalize(np.array([3.0, 4.0], dtype=np.float32))

    assert np.allclose(from_blob(to_blob(vector)), vector)
    assert from_blob(to_blob(vector)).dtype == np.float32


async def test_embedding_no_texts_returns_no_vectors():
    assert await FakeEmbedder().embed([]) == []
