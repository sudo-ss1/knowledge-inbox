"""A bounded in-process job queue.

Two workers is deliberate: it caps concurrent embedding calls so a bulk paste
of URLs degrades into a slower queue rather than a wall of 429s. The handler
is injected, so this module knows nothing about items or databases.
"""

import asyncio
from collections.abc import Awaitable, Callable

from ..logging import get_logger

log = get_logger(__name__)

Handler = Callable[[str], Awaitable[None]]


class IngestQueue:
    def __init__(self, handler: Handler, workers: int = 2) -> None:
        self._handler = handler
        self._requested_workers = max(1, workers)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    @property
    def worker_count(self) -> int:
        return len(self._tasks)

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._worker(index), name=f"ingest-worker-{index}")
            for index in range(self._requested_workers)
        ]
        log.info("ingest_workers_started", workers=len(self._tasks))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        log.info("ingest_workers_stopped")

    async def submit(self, item_id: str) -> None:
        await self._queue.put(item_id)

    async def drain(self) -> None:
        """Wait for the backlog to clear. Used by tests and shutdown."""
        await self._queue.join()

    async def _worker(self, index: int) -> None:
        while True:
            item_id = await self._queue.get()
            try:
                await self._handler(item_id)
            except Exception as exc:
                log.error("ingest_worker_error", exc_info=exc, item_id=item_id, worker=index)
            finally:
                self._queue.task_done()
