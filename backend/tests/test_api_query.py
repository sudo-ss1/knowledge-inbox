import pytest

from app.rag.answerer import ABSTENTION_MESSAGE, Answerer, FakeLlm
from app.rag.chunker import Chunk
from app.rag.retriever import Retriever


async def _seed_ready_item(context, *, title, text, source_url=None):
    items, chunks, embedder = context["items"], context["chunks"], context["embedder"]
    item = await items.create(
        type="url" if source_url else "note",
        source_url=source_url,
        title=title,
        raw_content=text,
    )
    await chunks.insert_many(
        item.id, [Chunk(0, text, len(text.split()))], await embedder.embed([text]), embedder.model
    )
    await items.mark_ready(item.id)
    return item


def _install_answerer(context, scripted: str, threshold: float = 0.05):
    context["app"].state.answerer = Answerer(
        retriever=Retriever(context["chunks"], context["embedder"]),
        llm=FakeLlm(scripted),
        threshold=threshold,
    )


async def test_a_grounded_query_returns_the_answer_and_its_sources(context):
    item = await _seed_ready_item(
        context,
        title="Kafka Docs",
        text="A rebalance is triggered when consumer group membership changes.",
        source_url="https://kafka.test/docs",
    )
    _install_answerer(context, "Membership changes trigger it [1].")

    res = await context["client"].post(
        "/query", json={"question": "what triggers a rebalance?"}
    )

    assert res.status_code == 200
    body = res.json()
    assert body["abstained"] is False
    assert body["answer"] == "Membership changes trigger it [1]."
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert source["marker"] == 1
    assert source["item_id"] == item.id
    assert source["title"] == "Kafka Docs"
    assert source["source"] == "https://kafka.test/docs"
    assert source["snippet"].startswith("A rebalance is triggered")
    assert 0.0 <= source["score"] <= 1.0


async def test_timings_are_reported(context):
    await _seed_ready_item(context, title="T", text="alpha beta gamma")
    _install_answerer(context, "Grounded [1].")

    body = (await context["client"].post("/query", json={"question": "alpha beta"})).json()

    assert set(body["timings_ms"]) == {"embed", "retrieve", "llm"}


async def test_an_abstention_is_a_200_not_an_error(context):
    await _seed_ready_item(context, title="Bread", text="sourdough starter hydration ratios")
    _install_answerer(context, "irrelevant", threshold=0.99)

    res = await context["client"].post(
        "/query", json={"question": "what triggers a kafka rebalance?"}
    )

    assert res.status_code == 200
    assert res.json() == {
        "answer": ABSTENTION_MESSAGE,
        "sources": [],
        "abstained": True,
        "timings_ms": res.json()["timings_ms"],
    }


async def test_querying_an_empty_inbox_abstains(context):
    _install_answerer(context, "should not matter")

    body = (await context["client"].post("/query", json={"question": "anything at all"})).json()

    assert body["abstained"] is True
    assert body["sources"] == []


async def test_top_k_defaults_to_the_configured_value(context):
    for index in range(8):
        await _seed_ready_item(context, title=f"T{index}", text=f"alpha beta chunk {index}")
    _install_answerer(context, " ".join(f"[{n}]" for n in range(1, 9)))

    body = (await context["client"].post("/query", json={"question": "alpha beta"})).json()

    assert len(body["sources"]) == context["settings"].retrieval_top_k


async def test_an_explicit_top_k_is_honored(context):
    for index in range(8):
        await _seed_ready_item(context, title=f"T{index}", text=f"alpha beta chunk {index}")
    _install_answerer(context, " ".join(f"[{n}]" for n in range(1, 9)))

    body = (
        await context["client"].post(
            "/query", json={"question": "alpha beta", "top_k": 2}
        )
    ).json()

    assert len(body["sources"]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "hi"},
        {"question": ""},
        {},
        {"question": "valid question", "top_k": 0},
        {"question": "valid question", "top_k": 99},
    ],
)
async def test_invalid_query_payloads_are_422(context, payload):
    _install_answerer(context, "x")

    res = await context["client"].post("/query", json=payload)

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


async def test_query_without_a_key_is_a_503(context):
    context["app"].state.settings = context["settings"].model_copy(
        update={"openai_api_key": None}
    )
    _install_answerer(context, "x")

    res = await context["client"].post("/query", json={"question": "a real question"})

    assert res.status_code == 503
    assert res.json()["error"]["code"] == "embedder_unavailable"
