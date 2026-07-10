"""Background task queue for AI Personal OS (T6.2).

A generic, in-process background task queue: a fixed-size pool of daemon
worker threads pulling jobs off a queue and executing them. It knows nothing
about ingestion, storage, or any other domain concern — it runs arbitrary
zero-argument callables only. ``main.py`` is what closes a specific
``process_registered_file(...)`` call into a submitted job; this module never
imports anything from ``aipos``.

v1 is exactly what Design Doc §A9 permits: "a simple in-process worker pool"
using only the standard library (``threading``, ``queue``) — no SQLite-backed
job table. ``§A9`` says a job table "can be" used, not "must be"; T6.1's
``files.status`` + ``storage.get_in_progress_files()`` already gives ingestion
jobs durable crash recovery, so a second, duplicate durability mechanism isn't
needed for Phase 1 (see the T6.2 architecture analysis). No event bus (the
frozen event bus, Build Plan T5.4, was never built in this project), no
scheduler, no external broker, no multiprocessing, no async/await.

Callers depend on the ``TaskQueue`` protocol (dependency injection, consistent
with the rest of this codebase), so tests can inject a fake instead of running
real threads. Constructor DI throughout: worker count and the queue are fixed
at construction; no globals, no singletons — callers own the instance's
lifetime explicitly (``main.py`` constructs exactly one).
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Design Doc §A9: "a simple in-process worker pool" — a small, fixed count.
DEFAULT_WORKER_COUNT = 4

Job = Callable[[], None]

# Sentinel enqueued once per worker so its blocking get() unblocks on stop().
_SHUTDOWN = object()


@runtime_checkable
class TaskQueue(Protocol):
    """Runs submitted jobs on background workers.

    Fully generic: implementations execute ``Job`` (``Callable[[], None]``)
    without any knowledge of what a job does. Callers are responsible for
    closing over whatever a job needs — e.g. its own storage connections.
    """

    def submit(self, job: Job) -> None:
        ...

    def stop(self, *, wait: bool = False) -> None:
        ...


class ThreadPoolTaskQueue:
    """TaskQueue backed by ``queue.Queue`` and a fixed pool of daemon threads.

    Each worker loops: pull a job, run it, repeat. A job that raises is
    logged and swallowed — the defensive try/except mirrors the isolation
    pattern already used throughout this codebase (``sources.py``'s
    ``_guarded()``, ``ingest.py``'s ``resume_pending()``) so one bad job never
    kills its worker thread; the next job it pulls still runs. Workers are
    daemon threads, so an un-stopped queue never blocks process exit.
    """

    def __init__(self, worker_count: int = DEFAULT_WORKER_COUNT) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be at least 1")
        self._queue: queue.Queue = queue.Queue()
        self._workers = [
            threading.Thread(target=self._run, daemon=True, name=f"aipos-worker-{i}")
            for i in range(worker_count)
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, job: Job) -> None:
        """Enqueue ``job`` to run on the next free worker. Never blocks."""
        self._queue.put(job)

    def stop(self, *, wait: bool = False) -> None:
        """Stop accepting new work by signalling every worker to exit.

        Each worker finishes whatever is ahead of the shutdown sentinel in
        the queue (including a job it is currently running) and then exits.
        With ``wait=False`` (the default) this returns immediately without
        blocking on that draining — any file left mid-pipeline when the
        process actually exits is indistinguishable from a crash, and
        ``ingest.resume_pending()`` (T6.1) already exists to recover it on the
        next startup, so a non-blocking stop is an intentional choice, not an
        oversight. ``wait=True`` blocks until every worker thread has exited.
        """
        for _ in self._workers:
            self._queue.put(_SHUTDOWN)
        if wait:
            for worker in self._workers:
                worker.join()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is _SHUTDOWN:
                return
            try:
                job()
            except Exception:
                logger.exception("Unhandled exception in background task queue job")
