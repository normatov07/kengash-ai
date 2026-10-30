"""Time each UI view against a store: `uv run python scripts/bench_views.py ~/.kengash`.

Manual, not in CI: timings depend on the machine. SP7 targets every view under 1 s warm on
a store of 1,500 tickets and 30,000 journal events.
"""

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path


def main(store: Path) -> int:
    os.environ["KENGASH_HOME"] = str(store)
    from kengash_ai.ops import views  # after KENGASH_HOME: the store is read at call time

    checks: list[tuple[str, Callable[[], object]]] = [
        ("overview", lambda: views.overview(window="today")),
        ("board", lambda: views.board(project=None)),
        ("memory", lambda: views.memory_view(project=None)),
        ("agents", lambda: views.agents_view(project=None, detect=False)),
        ("workflows", lambda: views.workflows_view(project=None)),
        ("settings", lambda: views.settings_view(project=None)),
    ]
    for name, view in checks:
        runs = []
        for _ in range(3):
            start = time.perf_counter()
            view()
            runs.append(time.perf_counter() - start)
        print(f"{name:10s} first {runs[0] * 1000:7.0f} ms   warm {min(runs[1:]) * 1000:7.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).expanduser()))
