"""The UI's API: token cookie, Host check, POST header, JSON, events (SP5 spec decision 4)."""

import asyncio
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from super_harness import journal
from super_harness.model import Doc, Event, ProviderStatus, Ticket
from super_harness.ops import agents, jobs, views
from super_harness.store import StorePaths, documents
from super_harness.ui import app as ui_app

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
    paused = client.post("/api/pause", headers={"X-Harness": "1"})
    assert paused.status_code == 200 and paused.json()["project"] is None
    assert client.post("/api/resume", headers={"X-Harness": "1"}).json() == {"started": []}


def test_a_foreign_origin_is_refused(client: TestClient) -> None:
    signed_in(client)
    evil = {"X-Harness": "1", "Origin": "http://evil.example"}
    assert client.post("/api/pause", headers=evil).status_code == 403
    own = {"X-Harness": "1", "Origin": f"http://127.0.0.1:{PORT}"}
    assert client.post("/api/pause", headers=own).status_code == 200
    assert client.post("/api/resume", headers={"X-Harness": "1"}).status_code == 200


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


POST = {"X-Harness": "1"}


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
    (registered_repo / ".harness").unlink()
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
    (other / ".harness").mkdir()
    signed_in(client)
    assert [f["repo"] for f in client.get("/api/links").json()["nearby"]] == [str(other)]
    adopted = client.post("/api/links/adopt", json={"path": str(other)}, headers=POST).json()
    assert adopted["nearby"] == [] and adopted["total"] == 2
    assert (other / ".harness").is_symlink()


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
    assert {role["role"] for role in shown["roster"]} >= {"planner", "implementer"}
    assert all(card["hint"] == "install it" for card in shown["providers"])


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
