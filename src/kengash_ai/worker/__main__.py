"""`python -m kengash_ai.worker ticket <id> [--steps N] [--project SLUG]`,
`plan-review <id> [--project SLUG]`, `compact`, or `harvest`.

A frontend for one detached job, as `cli` is for commands: it heartbeats, turns SIGTERM
into an orderly exit (the running CLI goes down with it), and calls `ops`.
"""

import argparse
import signal
import sys
import threading
import traceback
from collections.abc import Callable
from types import FrameType

from kengash_ai.ops import compaction, harvest, jobs, relay, reviews, steps

HEARTBEAT_S = 15
STOPPED = 143

type Job = tuple[str, Callable[[], str], Callable[[str], None]]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    job_id, run, fail = _job(args)
    signal.signal(signal.SIGTERM, _stop)
    done = threading.Event()
    beat = threading.Thread(target=_beat, args=(job_id, done), daemon=True)
    beat.start()
    try:
        print(run(), flush=True)
        return 0
    except Exception as exc:
        traceback.print_exc()
        fail(f"worker error: {exc}; log: runtime/logs/{job_id}.log")
        return 1
    finally:
        done.set()
        jobs.forget(job_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kengash_ai.worker")
    kinds = parser.add_subparsers(dest="job", required=True)
    ticket = kinds.add_parser("ticket", help="run a ticket's steps")
    ticket.add_argument("id")
    ticket.add_argument("--steps", type=int, default=None)
    ticket.add_argument("--project", default=None)
    review = kinds.add_parser("plan-review", help="run one review round of a plan")
    review.add_argument("id")
    review.add_argument("--project", default=None)
    kinds.add_parser("compact", help="compact MEMORY.md")
    kinds.add_parser("harvest", help="record what the user settled")
    return parser


def _job(args: argparse.Namespace) -> Job:
    """The job's worker id, its body, and what to do when the body fails."""
    if args.job == "compact":
        return jobs.COMPACT, compaction.run_compaction, compaction.fail_compaction
    if args.job == "harvest":
        return jobs.HARVEST, harvest.run_harvest, harvest.fail_harvest
    if args.job == "plan-review":
        return (
            args.id,
            lambda: reviews.run_review(args.id, project=args.project),
            lambda reason: reviews.fail_review(args.id, project=args.project, reason=reason),
        )

    def ticket() -> str:
        end = steps.run_job(
            args.id, project=args.project, steps=args.steps, on_new_tickets=relay.advance_quietly
        )
        relay.advance_quietly()  # the next tickets start (SP17 spec §3.4)
        return f"{args.id}: {end.status}: {end.reason}"

    def fail(reason: str) -> None:
        steps.fail_job(args.id, project=args.project, reason=reason)
        relay.advance_quietly()  # a failed ticket must not stall the rest of the loop

    return args.id, ticket, fail


def _stop(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(STOPPED)


def _beat(job_id: str, done: threading.Event) -> None:
    while not done.wait(HEARTBEAT_S):
        jobs.heartbeat(job_id)


if __name__ == "__main__":
    sys.exit(main())
