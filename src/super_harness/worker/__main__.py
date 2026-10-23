"""`python -m super_harness.worker ticket <id> [--steps N] [--project SLUG]`.

A frontend for one detached job, as `cli` is for commands: it heartbeats, turns SIGTERM
into an orderly exit (the running CLI goes down with it), and calls `ops`.
"""

import argparse
import signal
import sys
import threading
import traceback
from types import FrameType

from super_harness.ops import jobs, steps

HEARTBEAT_S = 15
STOPPED = 143


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m super_harness.worker")
    kinds = parser.add_subparsers(dest="job", required=True)
    ticket = kinds.add_parser("ticket", help="run a ticket's steps")
    ticket.add_argument("id")
    ticket.add_argument("--steps", type=int, default=None)
    ticket.add_argument("--project", default=None)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _stop)
    done = threading.Event()
    beat = threading.Thread(target=_beat, args=(args.id, done), daemon=True)
    beat.start()
    try:
        end = steps.run_job(args.id, project=args.project, steps=args.steps)
        print(f"{args.id}: {end.status}: {end.reason}", flush=True)
        return 0
    except Exception as exc:
        traceback.print_exc()
        reason = f"worker error: {exc}; log: runtime/logs/{args.id}.log"
        steps.fail_job(args.id, project=args.project, reason=reason)
        return 1
    finally:
        done.set()
        jobs.forget(args.id)


def _stop(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(STOPPED)


def _beat(ticket_id: str, done: threading.Event) -> None:
    while not done.wait(HEARTBEAT_S):
        jobs.heartbeat(ticket_id)


if __name__ == "__main__":
    sys.exit(main())
