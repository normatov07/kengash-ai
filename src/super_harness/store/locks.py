"""Inter-process locks under runtime/locks (system spec §4.3)."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from super_harness.model import HarnessError


@contextmanager
def locked(path: Path, timeout: float = 30.0) -> Iterator[None]:
    """Hold an exclusive lock on `path` for the duration of the block."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(path, timeout=timeout)
    try:
        lock.acquire()
    except Timeout as exc:
        message = f"store busy: {path.name} held by another process for {timeout:g}s"
        raise HarnessError(message) from exc
    try:
        yield
    finally:
        lock.release()
