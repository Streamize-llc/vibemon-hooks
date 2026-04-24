"""Cross-platform FileLock semantics — must serialize concurrent acquirers."""

import os
import tempfile
import threading
import time

from lock import FileLock


def test_filelock_creates_sentinel_file():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "settings.json")
        with FileLock(target):
            assert os.path.exists(target + ".vibemon.lock"), \
                "FileLock should create <path>.vibemon.lock as sentinel"


def test_filelock_serializes_concurrent_writers():
    """Two threads incrementing a counter under FileLock must reach 2N
    even with no internal synchronization. If the lock leaks, race
    conditions cause the counter to drop below N+M."""
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "settings.json")
        counter_path = os.path.join(d, "counter")
        with open(counter_path, "w", encoding="utf-8") as f:
            f.write("0")

        N = 100
        ITERS_PER_THREAD = N

        def worker():
            for _ in range(ITERS_PER_THREAD):
                with FileLock(target):
                    with open(counter_path, encoding="utf-8") as f:
                        v = int(f.read())
                    # Tiny sleep widens the race window — ensures the test
                    # would fail without the lock.
                    time.sleep(0.0001)
                    with open(counter_path, "w", encoding="utf-8") as f:
                        f.write(str(v + 1))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()
        t1.join(); t2.join()

        with open(counter_path) as f:
            final = int(f.read())
        assert final == 2 * ITERS_PER_THREAD, \
            f"FileLock leaked: expected {2 * ITERS_PER_THREAD}, got {final}"


def test_filelock_releases_on_exception():
    """Exception inside the with-block must still release the lock so
    subsequent acquires don't deadlock."""
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "settings.json")
        try:
            with FileLock(target):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        # Re-acquire — would deadlock if lock leaked
        with FileLock(target):
            pass
