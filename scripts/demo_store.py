"""Seed a demo store for checking the UI (SP5 spec decision 11).

    uv run python scripts/demo_store.py /tmp/harness-demo
    HARNESS_HOME=/tmp/harness-demo/.harness uv run harness ui open

Builds three scratch repos, registers them, and writes plans, tickets in every column,
journal events with token counts and diffs, held slots and a conductor ping, settings
overrides in payments-api, CLI sessions and a branch with commits on 7b55e0c1, and memory
writes. Never touches the user's own store: the store lives under the given folder.
"""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECTS = ("payments-api", "web-dashboard", "etl-pipeline")
TICKETS: list[dict[str, Any]] = [
    # project, id, title, importance, status, step, loop, loop_max, provider, touches
    {
        "p": 0,
        "id": "4f2a1b7c",
        "title": "Retry webhook delivery with backoff",
        "imp": "standard",
        "status": "in_process/under_implementation",
        "step": "implement",
        "loop": 2,
        "max": 4,
        "provider": "codex",
        "touches": ["services/webhooks"],
    },
    {
        "p": 1,
        "id": "91c7a0d3",
        "title": "Stream loop events to the board over SSE",
        "imp": "standard",
        "status": "in_process/under_review",
        "step": "review_code",
        "loop": 3,
        "max": 4,
        "provider": "claude",
        "touches": ["web/board"],
        "findings": 3,
    },
    {
        "p": 2,
        "id": "d0841f9a",
        "title": "Backfill 2024 ledger rows without downtime",
        "imp": "critical",
        "status": "in_process/stalled",
        "step": "review_plan",
        "loop": 1,
        "max": 6,
        "touches": [],
    },
    {
        "p": 0,
        "id": "7b55e0c1",
        "title": "Rotate payment webhook signing keys",
        "imp": "critical",
        "status": "in_process/needs_approval",
        "step": "security",
        "loop": 6,
        "max": 6,
        "touches": ["services/webhooks/signing"],
        "findings": 2,
    },
    {
        "p": 1,
        "id": "2e19cc48",
        "title": "Empty-state copy for the board columns",
        "imp": "simple",
        "status": "in_process/under_planning",
        "step": "plan",
        "loop": 1,
        "max": 3,
        "provider": "antigravity",
        "touches": ["web/copy"],
    },
    {
        "p": 0,
        "id": "a91b3d07",
        "title": "Add idempotency keys to refund endpoint",
        "imp": "standard",
        "status": "in_queue/blocked",
        "step": None,
        "loop": 1,
        "max": 4,
        "touches": ["services/refunds"],
    },
    {
        "p": 1,
        "id": "c44e8812",
        "title": "Rename loop_count to loop_index in docs",
        "imp": "simple",
        "status": "in_queue/ready",
        "step": None,
        "loop": 1,
        "max": 3,
        "touches": ["docs"],
    },
    {
        "p": 2,
        "id": "f0127ae4",
        "title": "Move session tokens out of the log sink",
        "imp": "critical",
        "status": "in_queue/ready",
        "step": None,
        "loop": 1,
        "max": 6,
        "touches": [],
    },
    {
        "p": 2,
        "id": "3b8e14c2",
        "title": "Cache district reference lookups",
        "imp": "standard",
        "status": "in_process/waiting_slot",
        "step": "implement",
        "loop": 1,
        "max": 4,
        "touches": ["etl/lookups"],
    },
    {
        "p": 1,
        "id": "5ab61c90",
        "title": "Cap SETTINGS.md read to 80 lines",
        "imp": "simple",
        "status": "in_process/awaiting_merge",
        "step": None,
        "loop": 2,
        "max": 3,
        "touches": ["web/settings"],
    },
    {
        "p": 0,
        "id": "a3f90b21",
        "title": "Persist loop counters across restarts",
        "imp": "standard",
        "status": "done/merged",
        "step": None,
        "loop": 2,
        "max": 4,
        "touches": ["services/loop"],
    },
    {
        "p": 2,
        "id": "6e02bb73",
        "title": "Shell out tag parsing instead of regex",
        "imp": "simple",
        "status": "done/merged",
        "step": None,
        "loop": 1,
        "max": 3,
        "touches": ["etl/tags"],
    },
]


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


FEATURED = "7b55e0c1"  # the ticket with sessions and a branch of commits


def commit_work(repo: Path, ticket: Any) -> None:
    """Two loops of trailered commits on the ticket's branch, as workers write them."""
    git(repo, "checkout", "-q", "-b", ticket.branch)
    for loop, (name, body) in enumerate(
        (
            ("signing.py", "def verify(payload, header):\n    return True\n"),
            ("rotate.py", "def rotate(keyring):\n    keyring.promote()\n"),
        ),
        start=1,
    ):
        (repo / name).write_text(body, encoding="utf-8")
        git(repo, "add", name)
        trailers = (
            f"Harness-Ticket: {ticket.uuid}\nHarness-Step: implement\n"
            f"Harness-Loop: {loop}\nHarness-Model: codex/gpt-5-codex"
        )
        git(repo, "commit", "-q", "-m", f"{ticket.id}: loop {loop}\n\n{trailers}")
    git(repo, "checkout", "-q", "main")


def main(root: Path) -> int:
    os.environ["HARNESS_HOME"] = str(root / ".harness")
    from kengash_ai import journal, memory
    from kengash_ai.model import (
        ConductorPing,
        Doc,
        Event,
        Plan,
        Running,
        SessionRef,
        SlotEntry,
        SlotTable,
        Ticket,
        TicketState,
        utc_now,
    )
    from kengash_ai.ops import configure, projects
    from kengash_ai.store import StorePaths, documents, runtime

    paths = StorePaths.default()
    if paths.home.exists():
        print(f"{paths.home} exists already; pick an empty folder", file=sys.stderr)
        return 1
    now = utc_now()
    for slug in PROJECTS:
        repo = root / "code" / slug
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        (repo / "README.md").write_text(f"# {slug}\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "init")
        projects.init_project(repo)
        plan = Plan.model_validate(
            {
                "id": f"{PROJECTS.index(slug) + 1:x}0000000"[:8],
                "uuid": uuid4(),
                "project": slug,
                "title": f"{slug} roadmap",
                "mode": "grill",
                "status": "ticketed",
                "created": now - timedelta(hours=4),
                "updated": now - timedelta(hours=4),
            }
        )
        documents.save_plan(
            paths.project(slug), Doc(plan, {"Prompt": f"Make {slug} production ready."})
        )
    slots: list[SlotEntry] = []
    events: list[Event] = []
    for item in TICKETS:
        slug = PROJECTS[item["p"]]
        updated = now - timedelta(minutes=5 + 7 * TICKETS.index(item))
        ticket = Ticket.model_validate(
            {
                "id": item["id"],
                "uuid": uuid4(),
                "project": slug,
                "plan": f"{item['p'] + 1:x}0000000"[:8],
                "title": item["title"],
                "importance": item["imp"],
                "workflow": item["imp"],
                "status": item["status"],
                "step": item["step"],
                "loop": item["loop"],
                "loop_max": item["max"],
                "touches": item["touches"],
                "branch": f"hrn/{item['id']}",
                "tokens": (9000 + 3400 * item["loop"]) * item["loop"],
                "created": now - timedelta(hours=3),
                "updated": updated,
            }
        )
        findings = "\n".join(
            f"- medium · services/x.py:{n * 10} · finding {n} · fix {n}"
            for n in range(1, item.get("findings", 0) + 1)
        )
        sections = {"Scope": item["title"], "Acceptance": "- [ ] it works", "Findings": findings}
        if item["id"] == FEATURED:
            ticket.sessions = {
                "implementer": SessionRef(provider="codex", model="gpt-5-codex", id="demo-impl"),
                "security-reviewer": SessionRef(provider="claude", model="sonnet", id="demo-sec"),
            }
            commit_work(root / "code" / slug, ticket)
        documents.save_ticket(paths.project(slug), Doc(ticket, sections))
        provider = item.get("provider")
        if provider:
            slots.append(
                SlotEntry(
                    provider=provider, project=slug, ticket=item["id"], step=item["step"], pid=1
                )
            )
            log = paths.logs / f"{item['id']}-1.out"
            runtime.save_ticket_state(
                paths,
                item["id"],
                TicketState(running=Running(role="x", provider=provider, model="default", log=log)),
            )
        for loop in range(1, item["loop"] + 1):
            events.append(
                Event.model_validate(
                    {
                        "ts": updated - timedelta(minutes=3 * (item["loop"] - loop + 1)),
                        "type": "step.end",
                        "project": slug,
                        "ticket": item["id"],
                        "step": "implement" if loop % 2 else "review_code",
                        "provider": provider or ("codex" if loop % 2 else "claude"),
                        "loop": loop,
                        "verdict": "pass" if loop % 2 else "fail",
                        "tokens": {"in": 9000 + 1300 * loop, "out": 2100 * loop},
                        "added": 40 * loop if loop % 2 else 0,
                        "removed": 6 * loop if loop % 2 else 0,
                        "files": (1 + loop % 3) if loop % 2 else 0,
                        "fingerprints": [] if loop % 2 else ["f1", "f2", "f3"][: 1 + loop % 3],
                    }
                )
            )
        sub = item["status"].split("/")[1]
        if sub in ("needs_approval", "stalled", "awaiting_merge"):
            reason = {
                "needs_approval": f"loop cap {item['loop']}/{item['max']} in security review",
                "stalled": "planner and plan reviewer disagreed 3 rounds on the backfill",
                "awaiting_merge": "every step passed",
            }[sub]
            events.append(
                Event.model_validate(
                    {
                        "ts": updated,
                        "type": f"ticket.{sub}",
                        "project": slug,
                        "ticket": item["id"],
                        "status": item["status"],
                        "reason": reason,
                    }
                )
            )
        if sub == "merged":
            events.append(Event(ts=updated, type="ticket.merged", project=slug, ticket=item["id"]))
    for event in sorted(events, key=lambda e: e.ts):
        journal.append(paths, event)
    for text, why, decision in (
        ("Owner prefers rotation runbooks over inline docs", f"review of {FEATURED}", False),
        ("Webhook keys rotate through a keyring with a 48h overlap", f"plan of {FEATURED}", True),
    ):
        memory.add(paths, text, why, decision=decision, by="claude/opus")
    configure.save_settings(
        {
            "loop_max.critical": 8,
            "agents.doc-writer.on": True,
            "project.test_cmd": "uv run pytest -q",
        },
        project="payments-api",
        by="demo",
    )
    runtime.save_slots(paths, SlotTable(held=slots))
    runtime.save_ping(paths, ConductorPing(pid=os.getpid(), agent="claude", project=None))
    print(f"demo store at {paths.home}; run: HARNESS_HOME={paths.home} uv run harness ui open")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()) if len(sys.argv) == 2 else 2)
