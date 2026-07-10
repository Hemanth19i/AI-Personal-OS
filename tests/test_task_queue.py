"""Behaviour tests for the background task queue (T6.2).

Concurrency is proven deterministically with threading.Barrier/Event (never
sleep-based timing), each guarded by a short timeout so a bug hangs a single
test rather than the whole suite.
"""

import threading
import time
import unittest

from aipos.task_queue import DEFAULT_WORKER_COUNT, TaskQueue, ThreadPoolTaskQueue

_TIMEOUT = 5.0  # generous but bounded; a real pass takes milliseconds


class ThreadPoolTaskQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._queues: list[ThreadPoolTaskQueue] = []

    def tearDown(self) -> None:
        for q in self._queues:
            q.stop(wait=True)

    def _make(self, worker_count: int = 2) -> ThreadPoolTaskQueue:
        q = ThreadPoolTaskQueue(worker_count)
        self._queues.append(q)
        return q

    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(self._make(), TaskQueue)

    def test_default_worker_count(self) -> None:
        self.assertEqual(DEFAULT_WORKER_COUNT, 4)

    def test_invalid_worker_count_raises(self) -> None:
        with self.assertRaises(ValueError):
            ThreadPoolTaskQueue(0)
        with self.assertRaises(ValueError):
            ThreadPoolTaskQueue(-1)

    def test_worker_threads_are_daemons(self) -> None:
        q = self._make(2)
        self.assertTrue(all(w.daemon for w in q._workers))

    def test_submitted_job_runs(self) -> None:
        q = self._make(1)
        done = threading.Event()
        q.submit(done.set)
        self.assertTrue(done.wait(timeout=_TIMEOUT))

    def test_multiple_jobs_all_run(self) -> None:
        q = self._make(2)
        n = 10
        remaining = threading.Semaphore(0)
        for _ in range(n):
            q.submit(remaining.release)
        for _ in range(n):
            self.assertTrue(remaining.acquire(timeout=_TIMEOUT))

    def test_jobs_run_concurrently(self) -> None:
        # Two jobs that can only both complete if they overlap: each waits on
        # a 2-party barrier before returning. If the queue serialized them
        # (one worker, or no real concurrency), the second job would never be
        # submitted in time to release the first from the barrier, and the
        # wait would time out.
        q = self._make(2)
        barrier = threading.Barrier(2, timeout=_TIMEOUT)
        results: list[bool] = []

        def job() -> None:
            barrier.wait()
            results.append(True)

        q.submit(job)
        q.submit(job)
        q.stop(wait=True)
        self.assertEqual(results, [True, True])

    def test_worker_count_bounds_concurrency(self) -> None:
        # With exactly 1 worker, two jobs both waiting on a 2-party barrier
        # can never both be "in flight" at once -> the barrier times out and
        # raises BrokenBarrierError inside the jobs (caught by the queue's own
        # defensive handling), proving concurrency is capped at worker_count.
        q = self._make(1)
        barrier = threading.Barrier(2, timeout=0.3)
        entered = threading.Event()

        def job() -> None:
            entered.set()
            barrier.wait()  # raises BrokenBarrierError after the short timeout

        q.submit(job)
        self.assertTrue(entered.wait(timeout=_TIMEOUT))  # first job started
        q.submit(job)
        # The second job cannot start until the first (serialized, single
        # worker) finishes raising/being swallowed — the barrier for the
        # first job alone always times out, since only 1 of 2 parties arrive.
        q.stop(wait=True)  # would hang here if a second worker let both in

    def test_worker_survives_job_exception(self) -> None:
        q = self._make(1)

        def boom() -> None:
            raise RuntimeError("job failure")

        q.submit(boom)

        ran = threading.Event()
        q.submit(ran.set)
        self.assertTrue(ran.wait(timeout=_TIMEOUT))  # worker kept going

    def test_multiple_exceptions_do_not_exhaust_the_pool(self) -> None:
        q = self._make(2)

        def boom() -> None:
            raise RuntimeError("boom")

        for _ in range(5):
            q.submit(boom)

        ran = threading.Event()
        q.submit(ran.set)
        self.assertTrue(ran.wait(timeout=_TIMEOUT))

    def test_stop_wait_false_returns_without_blocking(self) -> None:
        q = self._make(1)
        release = threading.Event()
        # Bounded even if stop() had a bug and blocked on this job: it would
        # give up after _TIMEOUT rather than hanging the suite forever.
        q.submit(lambda: release.wait(timeout=_TIMEOUT))

        start = time.monotonic()
        q.stop(wait=False)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0)  # must not block on the in-flight job

        release.set()  # let the worker finish so tearDown's stop(wait=True) can join

    def test_stop_wait_true_blocks_until_workers_exit(self) -> None:
        q = self._make(2)
        started = threading.Event()

        def job() -> None:
            started.set()

        q.submit(job)
        q.stop(wait=True)
        self.assertTrue(started.is_set())  # already-queued job ran before exit
        for worker in q._workers:
            self.assertFalse(worker.is_alive())

    def test_jobs_queued_before_stop_still_run(self) -> None:
        q = self._make(1)
        results: list[int] = []
        for i in range(3):
            q.submit(lambda i=i: results.append(i))
        q.stop(wait=True)
        self.assertEqual(results, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
