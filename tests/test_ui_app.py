"""The UI's API: token cookie, Host check, POST header, JSON, events (SP5 spec decision 4)."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from super_harness import journal
from super_harness.model import Doc, Event, Ticket
from super_harness.ops import views
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


def test_overview_and_board_are_json(client: TestClient) -> None:
    signed_in(client)
    overview = client.get("/api/overview?window=7d").json()
    assert overview["projects"] == ["payments-api"] and overview["sessions"] == []
    assert client.get("/api/overview?window=year").status_code == 422
    board = client.get("/api/board").json()
    assert [column["key"] for column in board["columns"]][:2] == ["in_queue", "plan"]


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
