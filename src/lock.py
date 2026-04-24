"""
lock.py — Cross-platform exclusive file lock.

Wraps fcntl.flock (Unix) and msvcrt.locking (Windows) behind a single
context manager so merge_*.py can stay platform-agnostic. Used by the
settings.json merge code path to prevent corruption under concurrent
install.sh / install.ps1 runs from multiple AI coding sessions.

See vibemon-app/CLAUDE.md "Multi-Session Concurrency Invariants" #3.

Stdlib only.
"""

import os


IS_WINDOWS = os.name == "nt"


class FileLock:
    """Blocking exclusive lock on a sentinel file.

    Usage:
        with FileLock(settings_path):
            # critical section — read, modify, atomic-rename settings.json

    The sentinel file (`<path>.vibemon.lock`) lives next to the protected
    file. Lock semantics are blocking on both platforms.
    """

    def __init__(self, base_path):
        self.path = base_path + ".vibemon.lock"
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "w", encoding="utf-8")
        if IS_WINDOWS:
            import msvcrt
            # LK_LOCK = blocking exclusive on a single byte at offset 0.
            # Retries indefinitely until acquired.
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if IS_WINDOWS:
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
