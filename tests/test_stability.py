"""Behaviour tests for the write-completion guard."""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from aipos.stability import wait_until_stable


class WaitUntilStableTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_complete_file_is_stable(self) -> None:
        f = self.root / "done.txt"
        f.write_text("finished", encoding="utf-8")
        self.assertTrue(wait_until_stable(f, poll_interval=0.02, timeout=3.0))

    def test_missing_file_is_unstable(self) -> None:
        self.assertFalse(
            wait_until_stable(self.root / "absent.txt", poll_interval=0.02, timeout=1.0)
        )

    def test_growing_then_stable_waits_for_full_content(self) -> None:
        f = self.root / "growing.bin"
        f.write_bytes(b"")
        chunks = 20

        def writer() -> None:
            with f.open("ab") as handle:
                for _ in range(chunks):
                    handle.write(b"x" * 1024)
                    handle.flush()
                    time.sleep(0.02)  # cadence < poll so growth is always seen

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            self.assertTrue(wait_until_stable(f, poll_interval=0.1, timeout=8.0))
            self.assertEqual(f.stat().st_size, chunks * 1024)
        finally:
            thread.join()

    def test_never_stable_times_out(self) -> None:
        f = self.root / "never.bin"
        f.write_bytes(b"")
        stop = threading.Event()

        def writer() -> None:
            with f.open("ab") as handle:
                while not stop.is_set():
                    handle.write(b"y" * 512)
                    handle.flush()
                    time.sleep(0.02)

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            self.assertFalse(wait_until_stable(f, poll_interval=0.1, timeout=0.6))
        finally:
            stop.set()
            thread.join()


if __name__ == "__main__":
    unittest.main()
