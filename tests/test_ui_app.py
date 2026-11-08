"""The UI's API: token cookie, Host check, POST header, JSON, events (SP5 spec decision 4)."""

import asyncio
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import Engine
from fastapi.testclient import TestClient

from kengash_ai import journal
from kengash_ai.model import Doc, Event, ProviderStatus, Ticket
from kengash_ai.ops import agents, controls, jobs, merging, relay, views
from kengash_ai.store import StorePaths, documents
from kengash_ai.ui import app as ui_app

TOKEN = "t" * 43
PORT = 47123
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def client(registered_repo: Path) -> TestClient:
    return TestClient(ui_app.create_app(token=TOKEN, port=PORT), base_url=BASE)


def signed_in(client: TestClient) -> TestClient:
    assert client.get(f"/?token={TOKEN}", follow_redirects=False).status_code == 303
    return client


def test_the_token_link_sets_a_cookie_and_strips_itself(client: TestClient) -> None:
    first = client.get(f"/?token={TOKEN}", follow_redirects=False)
    assert first.headers["location"] == "/"
    cookie = first.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert client.get("/").status_code == 200


def test_requests_without_the_token_are_refused(client: TestClient) -> None:
    assert client.get("/").status_code == 401
    assert client.get("/api/overview").status_code == 401
    assert client.get(f"/?token={'x' * 43}", follow_redirects=False).status_code == 401
    bearer = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/overview", headers=bearer).status_code == 200


def test_a_foreign_host_is_refused(client: TestClient) -> None:
    signed_in(client)
    assert client.get("/api/overview", headers={"Host": "evil.example:80"}).status_code == 403
    assert client.get("/api/overview", headers={"Host": f"localhost:{PORT}"}).status_code == 200


def test_posts_need_the_harness_header(client: TestClient) -> None:
    signed_in(client)
    assert client.post("/api/pause").status_code == 403
    paused = client.post("/api/pause", headers={"X-Kengash": "1"})
    assert paused.status_code == 200 and paused.json()["project"] is None
    resumed = client.post("/api/resume", headers={"X-Kengash": "1"}).json()
    assert resumed == {"started": [], "skipped": {}}


def test_a_foreign_origin_is_refused(client: TestClient) -> None:
    signed_in(client)
    evil = {"X-Kengash": "1", "Origin": "http://evil.example"}
    assert client.post("/api/pause", headers=evil).status_code == 403
    own = {"X-Kengash": "1", "Origin": f"http://127.0.0.1:{PORT}"}
    assert client.post("/api/pause", headers=own).status_code == 200
    assert client.post("/api/resume", headers={"X-Kengash": "1"}).status_code == 200


def test_overview_and_board_are_json(client: TestClient) -> None:
    signed_in(client)
    overview = client.get("/api/overview?window=7d").json()
    assert overview["projects"] == ["payments-api"] and overview["sessions"] == []
    assert client.get("/api/overview?window=year").status_code == 422
    board = client.get("/api/board").json()
    assert [column["key"] for column in board["columns"]][:3] == ["in_queue", "plan", "implement"]


def test_errors_come_back_as_json(client: TestClient) -> None:
    signed_in(client)
    missing = client.get("/api/board?project=nope")
    assert missing.status_code == 400 and "nope" in missing.json()["error"]


def test_the_event_stream_sends_new_journal_events(store_paths: StorePaths) -> None:
    class Open:
        async def is_disconnected(self) -> bool:
            return False

    async def first() -> str:
        stream = ui_app.event_stream(Open(), views.journal_end(), poll_s=0.01)
        journal.append(store_paths, Event(type="ticket.moved", project="p", ticket="aaaaaaa1"))
        return await anext(stream)

    chunk = asyncio.run(first())
    assert chunk.startswith("event: journal\ndata: ")
    assert json.loads(chunk.split("data: ", 1)[1])["type"] == "ticket.moved"


def test_the_event_stream_ends_when_the_browser_goes_away(store_paths: StorePaths) -> None:
    class Gone:
        async def is_disconnected(self) -> bool:
            return True

    async def drain() -> list[str]:
        stream = ui_app.event_stream(Gone(), views.journal_end(), poll_s=0.01)
        return [chunk async for chunk in stream]

    assert asyncio.run(drain()) == []


POST = {"X-Kengash": "1"}


def test_ticket_actions_go_through_ops(
    client: TestClient, store_paths: StorePaths, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    signed_in(client)
    refused = client.post("/api/tickets/7b55e0c1/approve", json={}, headers=POST)
    assert refused.status_code == 400 and "not waiting for approval" in refused.json()["error"]
    parked = client.post("/api/tickets/7b55e0c1/park", json={"why": "later"}, headers=POST)
    assert parked.status_code == 200
    moved = client.post(
        "/api/tickets/7b55e0c1/move", json={"to": "in_queue", "why": "back"}, headers=POST
    )
    assert moved.json()["after"] == "in_queue/ready"
    assert client.post("/api/tickets/ffffffff/stop", headers=POST).status_code == 400
    assert client.post("/api/tickets/7b55e0c1/fly", headers=POST).status_code == 404


def test_the_overview_says_when_everything_is_paused(client: TestClient) -> None:
    signed_in(client)
    assert client.get("/api/overview").json()["paused"] is False
    client.post("/api/pause", headers=POST)
    assert client.get("/api/overview").json()["paused"] is True


def test_link_health_and_its_actions(client: TestClient, registered_repo: Path) -> None:
    signed_in(client)
    assert client.get("/api/links").json()["intact"] == 1
    (registered_repo / ".kengash").unlink()
    assert client.get("/api/links").json()["projects"][0]["fix"] == "repair"
    repaired = client.post("/api/links/repair", headers=POST).json()
    assert repaired["projects"][0]["state"] == "ok"
    moved = registered_repo.with_name("moved")
    registered_repo.rename(moved)
    relinked = client.post(
        "/api/links/relink", json={"project": "payments-api", "path": str(moved)}, headers=POST
    ).json()
    assert relinked["projects"][0]["repo"] == str(moved) and relinked["intact"] == 1


def test_adopt_merges_a_found_store(client: TestClient, registered_repo: Path) -> None:
    other = registered_repo.parent / "legacy-crm"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    (other / ".kengash").mkdir()
    signed_in(client)
    assert [f["repo"] for f in client.get("/api/links").json()["nearby"]] == [str(other)]
    adopted = client.post("/api/links/adopt", json={"path": str(other)}, headers=POST).json()
    assert adopted["nearby"] == [] and adopted["total"] == 2
    assert (other / ".kengash").is_symlink()


def test_settings_saves_and_refuses_invalid_values(
    client: TestClient, store_paths: StorePaths
) -> None:
    signed_in(client)
    shown = client.get("/api/settings?project=payments-api").json()
    assert shown["scope"] == "payments-api" and shown["set_here"] == []
    saved = client.post(
        "/api/settings?project=payments-api",
        json={"changes": {"loop_max.simple": 5}},
        headers=POST,
    )
    assert saved.status_code == 200 and saved.json()["set_here"] == ["loop_max.simple"]
    before = store_paths.project("payments-api").settings.read_text()
    bad = client.post(
        "/api/settings?project=payments-api",
        json={"changes": {"loop_max.simple": 0}},
        headers=POST,
    )
    assert bad.status_code == 400 and "loop_max.simple" in bad.json()["error"]
    assert store_paths.project("payments-api").settings.read_text() == before
    reset = client.post(
        "/api/settings?project=payments-api",
        json={"changes": {"loop_max.simple": None}},
        headers=POST,
    )
    assert reset.json()["set_here"] == []


def test_the_agents_screen_reads_one_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def detector(paths: StorePaths) -> Callable[[str], ProviderStatus]:
        return lambda name: ProviderStatus(name=name, installed=False, hint="install it")

    monkeypatch.setattr(agents, "detector", detector)
    monkeypatch.setattr(views, "_detected", {})
    signed_in(client)
    shown = client.get("/api/agents?project=payments-api&window=7d").json()
    assert shown["scope"] == "payments-api"
    assert {agent["role"] for agent in shown["agents"]} >= {"planner", "implementer"}
    assert [card["name"] for card in shown["providers"]] == ["claude", "codex", "antigravity"]
    assert {card["hint"] for card in shown["providers"]} == {"install it"}


def test_a_ticket_and_its_plan_are_served(
    client: TestClient, store_paths: StorePaths, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket("ddddddd1"))
    signed_in(client)
    shown = client.get("/api/tickets/ddddddd1")
    assert shown.status_code == 200 and shown.json()["meta"]["id"] == "ddddddd1"
    missing = client.get("/api/tickets/eeeeeee1")
    assert missing.status_code == 400 and "eeeeeee1" in missing.json()["error"]
    assert client.get("/api/tickets/ddddddd1/diff").status_code == 400  # no commits yet
    assert client.get("/api/plans/a1b2c3d4").status_code == 400  # no such plan file


def test_compaction_starts_once_from_the_ui(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[str] = []
    running: list[bool] = []

    def detector(paths: StorePaths) -> Callable[[str], ProviderStatus]:
        return lambda name: ProviderStatus(name=name, installed=True, signed_in=True)

    def start(paths: StorePaths, job: str, job_id: str, project: str, args: list[str]) -> int:
        started.append(job)
        running.append(True)
        return 1

    monkeypatch.setattr(agents, "detector", detector)
    monkeypatch.setattr(jobs, "alive", lambda paths, job_id: True if running else None)
    monkeypatch.setattr(jobs, "start", start)
    signed_in(client)
    assert client.post("/api/memory/compact", headers=POST).json() == {"started": True}
    assert client.post("/api/memory/compact", headers=POST).json() == {"started": True}
    assert started == ["compact"]
    assert client.get("/api/memory").json()["cap"] == 200


def test_two_servers_on_one_host_keep_their_own_sign_in(registered_repo: Path) -> None:
    first = TestClient(ui_app.create_app(token=TOKEN, port=PORT), base_url=BASE)
    cookie = first.get(f"/?token={TOKEN}", follow_redirects=False).headers["set-cookie"]
    assert cookie.startswith(f"kengash_token_{PORT}=")  # cookies ignore ports; the name must not


NEW_AGENT = {
    "project": "payments-api",
    "role": "perf-reviewer",
    "kind": "review",
    "does": "Flag N+1 queries.",
    "cli": "claude/sonnet",
    "step": "perf_review",
    "workflows": ["critical"],
    "after": "review_code",
}


def test_new_agent_endpoint_saves_and_needs_the_header(
    client: TestClient, store_paths: StorePaths
) -> None:
    signed_in(client)
    assert client.post("/api/agents", json=NEW_AGENT).status_code == 403
    added = client.post("/api/agents", json=NEW_AGENT, headers=POST)
    assert added.status_code == 200, added.text
    roles = {row["role"]: row for row in added.json()["agents"]}
    assert (roles["perf-reviewer"]["builtin"], roles["perf-reviewer"]["step"]) == (
        False,
        "perf_review",
    )
    builtin = client.post("/api/agents", json=NEW_AGENT | {"role": "code-reviewer"}, headers=POST)
    assert builtin.status_code == 400 and "exists" in builtin.json()["error"]


def test_remove_agent_endpoint(client: TestClient) -> None:
    signed_in(client)
    client.post("/api/agents", json=NEW_AGENT, headers=POST)
    removed = client.post(
        "/api/agents/perf-reviewer/remove", json={"project": "payments-api"}, headers=POST
    )
    assert removed.status_code == 200
    assert "perf-reviewer" not in {row["role"] for row in removed.json()["agents"]}


def test_edit_copy_endpoints_need_the_header_and_refuse_cleanly(
    client: TestClient, store_paths: StorePaths
) -> None:
    signed_in(client)
    client.post("/api/agents", json=NEW_AGENT | {"instructions": "Fast.\n"}, headers=POST)
    patch = {"project": "payments-api", "patch": {"cli": "codex", "instructions": "Faster.\n"}}
    assert client.post("/api/agents/perf-reviewer", json=patch).status_code == 403
    edited = client.post("/api/agents/perf-reviewer", json=patch, headers=POST)
    assert edited.status_code == 200, edited.text
    perf = {row["role"]: row for row in edited.json()["agents"]}["perf-reviewer"]
    assert (perf["cli"], perf["instructions"], perf["instructions_own"]) == (
        "codex",
        "Faster.\n",
        True,
    )
    before = (store_paths.defaults / "SETTINGS.md").read_bytes()
    fixed = client.post("/api/agents/planner", json={"patch": {"kind": "read"}}, headers=POST)
    assert fixed.status_code == 400 and "planner is a built-in agent" in fixed.json()["error"]
    assert (store_paths.defaults / "SETTINGS.md").read_bytes() == before
    copied = client.post(
        "/api/agents/code-reviewer/copy", json={"new": "strict-reviewer"}, headers=POST
    )
    assert copied.status_code == 200
    assert "strict-reviewer" in {row["role"] for row in copied.json()["agents"]}


SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


def test_every_response_carries_the_security_headers(client: TestClient) -> None:
    responses = [
        client.get("/"),  # 401: not signed in
        client.get("/api/overview", headers={"Host": "evil.example:80"}),  # 403
        client.get(f"/?token={TOKEN}", follow_redirects=False),  # 303 with the cookie
    ]
    signed_in(client)
    responses += [client.get("/"), client.get("/static/app.js"), client.get("/api/meta")]
    assert [r.status_code for r in responses] == [401, 403, 303, 200, 200, 200]
    for response in responses:
        assert {k: response.headers.get(k) for k in SECURITY_HEADERS} == SECURITY_HEADERS


def test_the_0_1_change_header_is_refused(client: TestClient) -> None:
    signed_in(client)
    assert client.post("/api/pause", headers={"X-Harness": "1"}).status_code == 403
    assert client.post("/api/resume", headers=POST).status_code == 200


def test_a_role_skill_is_served_for_its_preview(
    client: TestClient, store_paths: StorePaths
) -> None:
    signed_in(client)
    shown = client.get("/api/skills/review-code?project=payments-api").json()
    assert (shown["name"], shown["source"]) == ("review-code", "package")
    assert shown["text"].startswith("# Code reviewer")
    assert client.get("/api/skills/nope").status_code == 400


def test_workflow_endpoints_create_rename_and_refuse(
    client: TestClient, store_paths: StorePaths, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    signed_in(client)
    assert client.post("/api/workflows", json={"name": "hotfix"}).status_code == 403
    made = client.post("/api/workflows", json={"name": "hotfix", "from": "simple"}, headers=POST)
    assert made.status_code == 200 and "hotfix" in made.json()["names"]
    renamed = client.post("/api/workflows/hotfix/rename", json={"new": "quickfix"}, headers=POST)
    assert renamed.status_code == 200 and "quickfix" in renamed.json()["names"]
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket("aa11bb22", workflow="quickfix"))
    refused = client.post("/api/workflows/quickfix/remove", json={}, headers=POST)
    assert (
        refused.status_code == 400 and "used by open tickets: aa11bb22" in refused.json()["error"]
    )
    shipped = client.post("/api/workflows/critical/remove", json={}, headers=POST)
    assert shipped.status_code == 400 and "ships with kengash" in shipped.json()["error"]


def test_the_overview_carries_loops_and_auto_mode(client: TestClient) -> None:
    signed_in(client)
    overview = client.get("/api/overview").json()
    assert (overview["loops"], overview["auto_default"], overview["auto"]) == (
        [],
        False,
        {"payments-api": False},
    )
    saved = client.post(
        "/api/settings?project=payments-api",
        json={"changes": {"loop_start": "auto"}},
        headers=POST,
    )
    assert saved.status_code == 200 and saved.json()["values"]["loop_start"] == "auto"
    assert client.get("/api/overview").json()["auto"] == {"payments-api": True}


def test_live_streams_history_then_done(client: TestClient, busy_ticket: Engine) -> None:
    signed_in(client)
    doc = busy_ticket.ticket()
    doc.meta.status, doc.meta.step = "done/merged", None
    documents.save_ticket(busy_ticket.paths.project(busy_ticket.slug), doc)
    with client.stream("GET", f"/api/tickets/{busy_ticket.ticket_id}/live") as response:
        body = response.read().decode()
    chunks = [chunk for chunk in body.split("\n\n") if chunk.strip()]
    assert chunks[0].startswith("event: activity\ndata: ")
    assert '"text": "read /work/pubspec.yaml"' in body
    assert chunks[-1] == "event: done\ndata: {}"


def test_a_merge_from_the_ui_starts_what_it_freed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    def merged(*_: object, **__: object) -> dict[str, str]:
        order.append("merged")
        return {"status": "done/merged"}

    def advanced() -> list[str]:
        order.append("relayed")
        return []

    monkeypatch.setattr(merging, "merge_ticket", merged)
    monkeypatch.setattr(relay, "advance_quietly", advanced)
    answer = signed_in(client).post(
        "/api/tickets/aaaa1111/merge", headers={"X-Kengash": "1"}, json={}
    )
    assert answer.status_code == 200
    assert order == ["merged", "relayed"]


def _noting(order: list[str], name: str, value: object = None) -> Callable[..., Any]:
    def note(*_: object, **__: object) -> Any:
        order.append(name)
        return value

    return note


def test_an_approval_from_the_ui_can_start_the_next_tickets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    monkeypatch.setattr(
        controls,
        "approve_ticket",
        _noting(order, "approved", {"status": "done/merged"}),
    )
    monkeypatch.setattr(relay, "advance_quietly", _noting(order, "relayed", []))
    answer = signed_in(client).post(
        "/api/tickets/aaaa1111/approve", headers={"X-Kengash": "1"}, json={}
    )
    assert answer.status_code == 200
    assert order == ["approved", "relayed"]


def test_a_resume_from_the_ui_can_start_the_next_tickets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    monkeypatch.setattr(controls, "resume", _noting(order, "resumed", controls.Resumed([])))
    monkeypatch.setattr(relay, "advance_quietly", _noting(order, "relayed", []))
    answer = signed_in(client).post("/api/resume", headers={"X-Kengash": "1"})
    assert answer.status_code == 200
    assert order == ["resumed", "relayed"]
