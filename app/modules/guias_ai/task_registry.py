from __future__ import annotations

import asyncio
import logging
import threading

logger = logging.getLogger(__name__)


class JobTaskRegistry:
    """Process-local registry of in-flight job asyncio tasks.

    The HTTP handler that creates a job stores the background task here. The
    cancel endpoint looks the task up and calls ``task.cancel()`` so the
    pipeline aborts at the next ``await`` point — preventing wasted LLM and
    Places calls after the user clicks "cancelar".

    This is intentionally in-memory: simple, single-process, and good enough
    for this BFF. If we ever shard the API, we'd need a coordination layer
    (Redis, Postgres LISTEN/NOTIFY).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, job_id: str, task: asyncio.Task) -> None:
        if not job_id:
            return
        with self._lock:
            self._tasks[job_id] = task
        task.add_done_callback(lambda _t, jid=job_id: self.discard(jid))

    def discard(self, job_id: str) -> None:
        with self._lock:
            self._tasks.pop(job_id, None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        logger.info("guias_ai.job.task_cancel_signaled job_id=%s", job_id)
        return True

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(job_id)
        return task is not None and not task.done()


_registry = JobTaskRegistry()


def get_registry() -> JobTaskRegistry:
    return _registry
