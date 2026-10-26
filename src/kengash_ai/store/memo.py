"""Content-keyed parse caches (SP7 spec decision 1).

Keys are digests of a file's bytes, not its stat: a file rewritten in place within one
timestamp tick keeps its size and inode, so only its content tells it apart. Reading a small
file is cheap; parsing its YAML is what these caches save. Callers get copies, never the
cached object.
"""

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable


def digest(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=16).digest()


class Memo[T]:
    """A thread-safe LRU of `maxsize` entries; `make` runs outside the lock."""

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._items: OrderedDict[Hashable, T] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_make(self, key: Hashable, make: Callable[[], T]) -> T:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        value = make()
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._maxsize:
                self._items.popitem(last=False)
        return value
