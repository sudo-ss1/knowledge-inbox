async def test_ingesting_a_note_returns_202_and_queues_it(context):
    res = await context["client"].post(
        "/ingest", json={"type": "note", "content": "Kafka rebalances on rejoin."}
    )

    assert res.status_code == 202
    body = res.json()
    assert body["id"].startswith("itm_")
    assert body["status"] == "pending"
    assert body["type"] == "note"
    assert context["queue"].submitted == [body["id"]]


async def test_ingesting_a_url_returns_202(context):
    res = await context["client"].post(
        "/ingest", json={"type": "url", "url": "https://example.com/post"}
    )

    assert res.status_code == 202
    assert res.json()["type"] == "url"


async def test_a_note_title_comes_from_its_first_line(context):
    res = await context["client"].post(
        "/ingest", json={"type": "note", "content": "Rebalance notes\nsecond line here"}
    )

    detail = await context["client"].get(f"/items/{res.json()['id']}")
    assert detail.json()["title"] == "Rebalance notes"


async def test_an_unknown_type_is_a_422_in_the_envelope(context):
    res = await context["client"].post("/ingest", json={"type": "audio", "content": "x"})

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"
    assert res.json()["error"]["request_id"].startswith("req_")


async def test_a_blank_note_is_rejected(context):
    res = await context["client"].post("/ingest", json={"type": "note", "content": "   "})

    assert res.status_code == 422


async def test_a_non_http_url_is_rejected(context):
    res = await context["client"].post("/ingest", json={"type": "url", "url": "ftp://x.test/a"})

    assert res.status_code == 422


async def test_ingest_without_a_key_is_a_503(context):
    context["app"].state.settings = context["settings"].model_copy(
        update={"openai_api_key": None}
    )

    res = await context["client"].post("/ingest", json={"type": "note", "content": "hello there"})

    assert res.status_code == 503
    assert res.json()["error"]["code"] == "embedder_unavailable"
    assert "OPENAI_API_KEY" in res.json()["error"]["message"]


async def test_items_list_is_newest_first_with_a_preview_and_no_raw_content(context):
    for index in range(3):
        await context["client"].post(
            "/ingest", json={"type": "note", "content": f"note number {index}"}
        )

    body = (await context["client"].get("/items")).json()

    assert next(item["preview"] for item in body["items"]) == "note number 2"
    assert "raw_content" not in body["items"][0]
    assert body["next_cursor"] is None


async def test_items_list_paginates_by_cursor(context):
    for index in range(3):
        await context["client"].post(
            "/ingest", json={"type": "note", "content": f"note {index}"}
        )

    first = (await context["client"].get("/items", params={"limit": 2})).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"]

    second = (
        await context["client"].get(
            "/items", params={"limit": 2, "cursor": first["next_cursor"]}
        )
    ).json()
    assert len(second["items"]) == 1


async def test_an_invalid_status_filter_is_a_422(context):
    res = await context["client"].get("/items", params={"status": "banana"})

    assert res.status_code == 422


async def test_item_detail_includes_raw_content(context):
    created = await context["client"].post(
        "/ingest", json={"type": "note", "content": "the full body"}
    )

    res = await context["client"].get(f"/items/{created.json()['id']}")

    assert res.status_code == 200
    assert res.json()["raw_content"] == "the full body"


async def test_an_unknown_item_is_a_404_in_the_envelope(context):
    res = await context["client"].get("/items/itm_doesnotexist")

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "item_not_found"


async def test_a_failed_item_exposes_its_error_to_the_ui(context):
    created = await context["client"].post(
        "/ingest", json={"type": "url", "url": "https://example.com/gone"}
    )
    item_id = created.json()["id"]

    async def fetch(url, **kwargs):
        from app.errors import ApiError

        raise ApiError("fetch_failed", "Upstream returned HTTP 404.", 502)

    await context["pipeline"](fetch).process(item_id)

    body = (await context["client"].get("/items")).json()
    assert body["items"][0]["status"] == "failed"
    assert body["items"][0]["error"] == "Upstream returned HTTP 404."


async def test_a_malformed_cursor_is_a_400(context):
    res = await context["client"].get("/items", params={"cursor": "not-a-real-cursor"})

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "bad_cursor"


async def test_status_and_cursor_compose(context):
    for index in range(3):
        created = await context["client"].post(
            "/ingest", json={"type": "note", "content": f"ready note {index}"}
        )
        await context["items"].mark_ready(created.json()["id"])
    await context["client"].post("/ingest", json={"type": "note", "content": "still pending"})

    first = (
        await context["client"].get("/items", params={"status": "ready", "limit": 2})
    ).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"]

    second = (
        await context["client"].get(
            "/items", params={"status": "ready", "limit": 2, "cursor": first["next_cursor"]}
        )
    ).json()
    assert len(second["items"]) == 1
    assert all(item["status"] == "ready" for item in second["items"])
