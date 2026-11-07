"""Desktop notifications when a ticket needs the user (SP13 spec §3.5)."""

import sys
from collections.abc import Callable

import pytest
from conftest import write_settings

from kengash_ai.model import Event
from kengash_ai.ops import notify, records
from kengash_ai.store import StorePaths


def found(*names: str) -> Callable[[str], str | None]:
    return lambda name: f"/usr/bin/{name}" if name in names else None


def event(kind: str, **fields: object) -> Event:
    data = {"type": kind, "project": "payments-api", "ticket": "7b55e0c1", **fields}
    return Event.model_validate(data)


def test_a_gate_notifies_with_its_reason_and_action() -> None:
    gate = event("ticket.needs_approval", reason="token cap: 1,010,000 of 1,000,000 used")
    assert notify.argv(gate, platform="linux", which=found("notify-send")) == [
        "notify-send",
        "-a",
        "kengash",
        "-u",
        "normal",
        "kengash · payments-api",
        "7b55e0c1 needs approval: token cap: 1,010,000 of 1,000,000 used"
        " · kengash approve 7b55e0c1",
    ]
    failed = notify.argv(
        event("ticket.failed", reason="crash: boom"), platform="linux", which=found("notify-send")
    )
    assert (
        failed is not None
        and failed[4] == "critical"
        and failed[-1].endswith("kengash run 7b55e0c1")
    )


def test_every_gate_and_a_plan_review_notify() -> None:
    kinds = ["ticket.stalled", "ticket.awaiting_merge"]
    for kind in kinds:
        assert notify.argv(event(kind), platform="linux", which=found("notify-send"))
    review = Event.model_validate(
        {
            "type": "plan.reviewed",
            "project": "payments-api",
            "plan": "a1b2c3d4",
            "round": 1,
            "verdict": "pass",
        }
    )
    line = notify.argv(review, platform="linux", which=found("notify-send"))
    assert line is not None and line[-1] == "plan a1b2c3d4 review round 1: pass"


def test_macos_uses_osascript() -> None:
    line = notify.argv(event("ticket.awaiting_merge"), platform="darwin", which=found("osascript"))
    assert line is not None and line[:2] == ["osascript", "-e"]
    assert line[2].startswith('display notification "7b55e0c1 is ready to merge')


def test_other_events_or_no_notifier_send_nothing() -> None:
    assert notify.argv(event("step.start"), platform="linux", which=found("notify-send")) is None
    assert notify.argv(event("ticket.failed"), platform="linux", which=found()) is None


def test_record_notifies_once_switched_on_and_never_raises(
    registered_repo: object, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[list[str]] = []

    def popen(argv: list[str], **kwargs: object) -> None:
        sent.append(argv)
        raise OSError("no session bus")

    monkeypatch.setattr(notify, "popen", popen)
    monkeypatch.setattr(notify, "which", found("notify-send"))
    monkeypatch.setattr(sys, "platform", "linux")
    gate = event("ticket.failed", reason="crash: boom")
    records.record(store_paths, "kengash: test", gate)  # KENGASH_WATCH=off in tests
    assert sent == []
    monkeypatch.delenv("KENGASH_WATCH")
    records.record(store_paths, "kengash: test", gate)
    assert len(sent) == 1  # Popen failed, and record went on
    write_settings(store_paths, "watch.notify: false\n")
    records.record(store_paths, "kengash: test", gate)
    assert len(sent) == 1


def test_macos_keeps_non_ascii_text() -> None:
    gate = event("ticket.failed", reason="crash: “quoted” — ünïcode")
    line = notify.argv(gate, platform="darwin", which=found("osascript"))
    assert line is not None and "“quoted” — ünïcode" in line[2] and "\\u" not in line[2]
