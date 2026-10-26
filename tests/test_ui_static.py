"""The UI's static screens: served without the token, and their template helper escapes
every interpolated value (SP5 spec decision 1)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from super_harness.ui import app as ui_app

NODE = shutil.which("node")  # found before the fake-CLI fixture narrows PATH
STATIC = Path(ui_app.__file__).parent / "static"


def test_every_module_is_served(registered_repo: Path) -> None:
    client = TestClient(ui_app.create_app(token="t", port=1), base_url="http://127.0.0.1:1")
    for path in [*sorted(STATIC.rglob("*.js")), STATIC / "app.css"]:
        response = client.get(f"/static/{path.relative_to(STATIC).as_posix()}")
        assert response.status_code == 200, path


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_templates_escape_every_value() -> None:
    script = (
        f"import {{ html, raw, render }} from '{(STATIC / 'html.js').as_uri()}';"
        "const title = '<script>alert(1)</script>';"
        "console.log(render(html`<b title=\"${'\"x'}\">${title}${[1, '<i>']}${raw('<hr>')}</b>`));"
    )
    done = subprocess.run(
        [str(NODE), "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == (
        '<b title="&quot;x">&lt;script&gt;alert(1)&lt;/script&gt;1&lt;i&gt;<hr></b>'
    )


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_every_module_parses() -> None:
    for path in sorted(STATIC.rglob("*.js")):
        subprocess.run([str(NODE), "--check", str(path)], check=True, capture_output=True)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_workflow_graph_lays_steps_out_left_to_right() -> None:
    script = (
        f"import {{ layout }} from '{(STATIC / 'graph.js').as_uri()}';"
        "const g = layout(['plan', 'implement', 'review_code'], {review_code: 'implement'});"
        "console.log(JSON.stringify({columns: g.columns, ids: g.nodes.map((n) => n.id),"
        " cols: g.nodes.map((n) => n.col), back: g.edges.filter((e) => e.kind === 'back'),"
        " pass: g.edges.filter((e) => e.kind === 'pass').length}));"
    )
    done = subprocess.run(
        [str(NODE), "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    found = json.loads(done.stdout)
    assert found["columns"] == 5
    assert found["ids"] == ["trigger", "plan", "implement", "review_code", "done"]
    assert found["cols"] == [0, 1, 2, 3, 4]
    assert found["back"] == [{"from": "review_code", "to": "implement", "kind": "back"}]
    assert found["pass"] == 4


def test_the_fonts_ship_with_the_screens(registered_repo: Path) -> None:
    client = TestClient(ui_app.create_app(token="t", port=1), base_url="http://127.0.0.1:1")
    for name in ("inter.woff2", "jetbrains-mono.woff2", "OFL.txt"):
        assert client.get(f"/static/fonts/{name}").status_code == 200
    assert client.get("/static/fonts/inter.woff2").headers["content-type"] == "font/woff2"
    css = (STATIC / "app.css").read_text()
    assert 'url("/static/fonts/inter.woff2")' in css and "fonts.googleapis" not in css


def test_screens_are_revalidated_so_an_upgrade_shows_at_once(registered_repo: Path) -> None:
    client = TestClient(ui_app.create_app(token="t", port=1), base_url="http://127.0.0.1:1")
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"
    assert client.get("/static/fonts/inter.woff2").headers["cache-control"] == "no-cache"


def css_rule(selector: str) -> dict[str, str]:
    """The declarations of the stylesheet's first top-level rule for `selector`."""
    css = (STATIC / "app.css").read_text()
    found = re.search(rf"^{re.escape(selector)} \{{([^}}]*)\}}", css, re.MULTILINE)
    assert found, selector
    pairs = (part.split(":", 1) for part in found[1].split(";") if part.strip())
    return {name.strip(): value.strip() for name, value in pairs}


def test_seven_board_columns_fit_a_1440_px_screen() -> None:
    strip, column = css_rule(".cols"), css_rule(".col")
    width, gap = (
        int(strip["--col-min"].removesuffix("px")),
        int(strip["--col-gap"].removesuffix("px")),
    )
    assert 150 <= width <= 160  # narrow enough for seven, wide enough for a card
    assert column["min-width"] == "var(--col-min)" and strip["gap"] == "var(--col-gap)"
    board = 1440 - 237 - 2 * 20  # the sidebar and its border, the board's side padding
    assert 7 * width + 6 * gap <= board
    assert "--n: ${cols.length}" in (STATIC / "views" / "board.js").read_text()
    assert css_rule(".card-top")["flex-wrap"] == "wrap"  # a narrow card wraps its loop dots


def test_agents_screen_offers_new_agent() -> None:
    agents = (STATIC / "views" / "agents.js").read_text()
    for text in ("New agent", "Reviewer", "Worker", "Advisor", '"/api/agents"', "Remove agent"):
        assert text in agents
    assert "showModal()" in agents  # a native dialog: focus stays inside, Escape closes it


def test_settings_status_flow_links_to_new_agent() -> None:
    assert "#/agents/new" in (STATIC / "views" / "settings.js").read_text()


def test_custom_steps_borrow_their_kinds_look() -> None:
    graph = (STATIC / "graph.js").read_text()
    assert "export function learnSteps" in graph
    assert "learnSteps(data.kinds)" in (STATIC / "views" / "workflow.js").read_text()


def test_board_titles_fit_seven_columns() -> None:
    css = (STATIC / "app.css").read_text()
    assert css_rule(".col")["container-type"] == "inline-size"
    narrow = re.search(r"@container \(max-width: (\d+)px\) \{(.*?)\n\}", css, re.S)
    assert narrow and int(narrow[1]) >= 156  # the 7-column width at 1440 px
    assert re.search(r"\.col-more \{[^}]*position: absolute", narrow[2])
    assert re.search(
        r"\.col-head:hover \.col-more, \.col-more:focus-visible \{[^}]*opacity: 1", narrow[2]
    )


def test_queue_footer_stays_on_one_line() -> None:
    assert css_rule(".col-add")["white-space"] == "nowrap"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_done_node_is_numbered() -> None:
    script = (
        f"import {{ canvas, layout }} from '{(STATIC / 'graph.js').as_uri()}';"
        f"import {{ render }} from '{(STATIC / 'html.js').as_uri()}';"
        "console.log(render(canvas(layout(['plan', 'implement', 'review_code'], {}))));"
    )
    done = subprocess.run(
        [str(NODE), "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    assert "<b>4 · Done</b>" in done.stdout and "<b>Trigger</b>" in done.stdout


def test_routing_names_the_critical_loop_cap() -> None:
    agents = (STATIC / "views" / "agents.js").read_text()
    assert "${data.loop_max[name]} loops" in agents


def test_an_unsupported_provider_card_explains_itself() -> None:
    assert "card.hint ||" in (STATIC / "views" / "agents.js").read_text()


def test_the_page_names_its_icon() -> None:
    index = (STATIC / "index.html").read_text()
    assert '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">' in index
    assert (STATIC / "favicon.svg").read_text().startswith("<svg")


def _contrast(fg: str, bg: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted([luminance(fg), luminance(bg)], reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_faint_text_meets_wcag_aa_on_every_surface() -> None:
    tokens = dict(re.findall(r"--([\w-]+): (#[0-9a-fA-F]{6});", (STATIC / "app.css").read_text()))
    surfaces = ["bg", "panel", "raised", "#191c21", "#1a1e22", "#14171a", "#121518"]
    for surface in surfaces:
        background = tokens.get(surface, surface)
        assert _contrast(tokens["faint"], background) >= 4.5, surface
    assert css_rule(".pstate.plain")["color"] == "var(--muted)"


def test_the_settings_file_view_scrolls_by_keyboard() -> None:
    settings = (STATIC / "views" / "settings.js").read_text()
    assert '<div class="yaml-box" tabindex="0" role="region" aria-label="SETTINGS.md">' in settings
