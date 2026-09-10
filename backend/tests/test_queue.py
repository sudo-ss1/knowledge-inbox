import asyncio

from app.ingest.queue import IngestQueue


async def test_submitted_ids_reach_the_handler():
    seen: list[str] = []
    queue = IngestQueue(handler=lambda item_id: _record(seen, item_id), workers=1)
    await queue.start()

    await queue.submit("itm_a")
    await queue.submit("itm_b")
    await queue.drain()
    await queue.stop()

    assert sorted(seen) == ["itm_a", "itm_b"]


async def _record(sink: list[str], item_id: str) -> None:
    sink.append(item_id)


async def test_a_failing_handler_does_not_kill_the_worker():
    processed: list[str] = []

    async def handler(item_id: str) -> None:
        if item_id == "itm_bad":
            raise RuntimeError("boom")
        processed.append(item_id)

    queue = IngestQueue(handler=handler, workers=1)
    await queue.start()

    await queue.submit("itm_bad")
    await queue.submit("itm_good")
    await queue.drain()
    await queue.stop()

    assert processed == ["itm_good"]


async def test_concurrency_is_capped_at_the_worker_count():
    in_flight = 0
    peak = 0

    async def handler(_: str) -> None:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1

    queue = IngestQueue(handler=handler, workers=2)
    await queue.start()

    for index in range(8):
        await queue.submit(f"itm_{index}")
    await queue.drain()
    await queue.stop()

    assert peak <= 2


async def test_stop_cancels_the_workers():
    queue = IngestQueue(handler=lambda _: asyncio.sleep(0), workers=2)
    await queue.start()

    await queue.stop()

    assert queue.worker_count == 0
