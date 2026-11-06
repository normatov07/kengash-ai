"""The UI's static screens: served without the token, and their template helper escapes
every interpolated value (SP5 spec decision 1)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kengash_ai.ui import app as ui_app

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
    for text in (
        "Copy as my agent",
        "Use a skill",
        "Write my own",
        "data-save-bar",
        "/api/skills/",
    ):
        assert text in agents


def test_builtin_editor_locks_role_and_instructions() -> None:
    agents = (STATIC / "views" / "agents.js").read_text()
    assert agents.count("locked: agent.builtin") == 1 and "{ locked: true }" in agents
    assert (
        'section("Instructions", html`<p class="ag-note">Built-in instructions are fixed' in agents
    )


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


def test_the_ui_wears_the_apps_name() -> None:
    assert "<title>Kengash AI</title>" in (STATIC / "index.html").read_text()
    assert "<b>kengash</b>" in (STATIC / "app.js").read_text()


def _node(script: str) -> str:
    assert NODE is not None
    done = subprocess.run(
        [str(NODE), "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_controls_helpers() -> None:
    controls = (STATIC / "controls.js").as_uri()
    found = json.loads(
        _node(
            f"import * as c from '{controls}';"
            "const cards = [{name: 'claude', installed: true, signed_in: true,"
            " models: ['opus', 'sonnet']},"
            " {name: 'codex', installed: false, signed_in: false, models: []}];"
            "console.log(JSON.stringify({"
            " move: c.moveItem(['a', 'b', 'c'], 2, 0), stay: c.moveItem(['a', 'b'], 0, -1),"
            " counts: c.counts('one two\\nthree\\n'), empty: c.counts(''),"
            " split: [c.splitCli('claude/opus[1m]'), c.splitCli('codex')],"
            " joined: [c.cliValue('claude', 'opus'), c.cliValue('codex', 'default'),"
            " c.cliValue('codex', '')],"
            " models: c.modelChoices(cards, 'claude', 'haiku'),"
            " none: c.modelChoices(cards, 'codex', 'default'),"
            " clis: c.cliChoices(cards, 'codex', true)}));"
        )
    )
    assert found["move"] == ["c", "a", "b"] and found["stay"] == ["a", "b"]
    assert found["counts"] == {"lines": 2, "words": 3} and found["empty"] == {
        "lines": 0,
        "words": 0,
    }
    assert found["split"] == [["claude", "opus[1m]"], ["codex", "default"]]
    assert found["joined"] == ["claude/opus", "codex", "codex"]
    assert found["models"] == [
        ["default", "default"],
        ["opus", "opus"],
        ["sonnet", "sonnet"],
        ["haiku", "haiku"],
        ["__other", "Other…"],
    ]
    assert found["none"] == [["default", "default"], ["__other", "Other…"]]
    assert found["clis"] == [
        ["claude", "claude", False],
        ["codex", "codex · not installed", False],
        ["antigravity", "antigravity · not detected", True],
        ["shell", "shell · runs project.test_cmd", False],
    ]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_controls_escape_what_they_render() -> None:
    controls = (STATIC / "controls.js").as_uri()
    html = (STATIC / "html.js").as_uri()
    out = _node(
        f"import * as c from '{controls}'; import {{ render }} from '{html}';"
        "console.log(render(c.select({id: 's', value: '<b>', options: [['<b>', '<b> \"x\"']]})));"
    )
    assert "<b>" not in out and "&lt;b&gt;" in out and "selected" in out


def test_breakpoints_exist() -> None:
    css = (STATIC / "app.css").read_text()
    for width in (1280, 900, 600):
        assert f"@media (max-width: {width}px)" in css, width


def test_nav_folds_into_a_menu() -> None:
    shell = (STATIC / "app.js").read_text()
    assert "data-nav-toggle" in shell and "aria-expanded" in shell and 'key === "Escape"' in shell
    assert css_rule(".nav-toggle")["display"] == "none"  # shown only on narrow screens


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_every_link_has_an_insert_port() -> None:
    graph = (STATIC / "graph.js").as_uri()
    html = (STATIC / "html.js").as_uri()
    out = _node(
        f"import {{ layout, canvas }} from '{graph}'; import {{ render }} from '{html}';"
        "const g = layout(['plan', 'implement', 'review_code'], {review_code: 'implement'});"
        "const page = render(canvas(g, {insert: true}));"
        'const found = [...page.matchAll(/data-insert-at="(\\d+)"/g)];'
        "console.log(JSON.stringify(found.map((m) => +m[1])));"
    )
    assert json.loads(out) == [0, 1, 2, 3]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_workflow_edits() -> None:
    flow = (STATIC / "views" / "workflow.js").as_uri()
    found = json.loads(
        _node(
            f"import * as w from '{flow}';"
            "const d = {steps: ['plan', 'implement', 'review_code', 'security'],"
            " on_fail: {review_code: 'implement', security: 'implement'}};"
            "const kinds = {plan: 'read', implement: 'edit', review_code: 'review',"
            " security: 'review',"
            " perf: 'review', tidy: 'edit'};"
            "console.log(JSON.stringify({"
            " back: w.backTargets(d.steps, 'review_code'),"
            " inserted: w.insertStep(d, 3, 'perf').steps,"
            " moved: w.moveStep(d, 'security', 1),"
            " swapReview: w.swapStep(d, 'review_code', 'perf', kinds).on_fail,"
            " swapEdit: w.swapStep(d, 'implement', 'tidy', kinds),"
            " swapToEdit: w.swapStep(d, 'security', 'tidy', kinds).on_fail,"
            " removed: w.removeStep(d, 'implement')}));"
        )
    )
    assert found["back"] == ["plan", "implement"]
    assert found["inserted"] == ["plan", "implement", "review_code", "perf", "security"]
    # a step moved above its send-back target loses that edge: edges only send back
    assert found["moved"] == {
        "steps": ["plan", "security", "implement", "review_code"],
        "on_fail": {"review_code": "implement"},
    }
    assert found["swapReview"] == {"perf": "implement", "security": "implement"}
    assert found["swapEdit"] == {
        "steps": ["plan", "tidy", "review_code", "security"],
        "on_fail": {"review_code": "tidy", "security": "tidy"},
    }
    assert found["swapToEdit"] == {"review_code": "implement"}
    assert found["removed"] == {"steps": ["plan", "review_code", "security"], "on_fail": {}}


def test_no_text_input_offers_a_datalist() -> None:
    for path in sorted((STATIC / "views").glob("*.js")):
        assert "list=" not in path.read_text(), path.name
    assert "datalist" not in (STATIC / "scope.js").read_text()


def test_settings_offers_planning_and_merging_as_real_controls() -> None:
    page = (STATIC / "views" / "settings.js").read_text()
    for key in (
        "plan.reviewer",
        "memory.compactor",
        "merge.mode",
        "grill.round_size",
        "plan.review_max",
        "loop_start",
    ):
        assert f'"{key}"' in page, key
    assert "modelPicker(" in page and "segmented(" in page and "toggle(" in page
    assert "Auto mode" in page


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_an_emptied_other_model_saves_the_default() -> None:
    controls = (STATIC / "controls.js").as_uri()
    out = _node(
        f"import {{ bindModelPicker }} from '{controls}';"
        "const fake = (value) => ({value, hidden: false, disabled: false, on: {},"
        " addEventListener(type, f) { this.on[type] = f; }, focus() {}, set innerHTML(x) {}});"
        "const els = {cli: fake('claude'), model: fake('__other'), other: fake('')};"
        "const picker = {querySelector: (s) => els[s.match(/part=(\\w+)/)[1]]};"
        "const got = []; bindModelPicker(picker, [], (v) => got.push(v));"
        "els.other.value = 'o'; els.other.on.input(); els.other.value = ''; els.other.on.input();"
        "console.log(JSON.stringify(got));"
    )
    assert json.loads(out) == ["claude/o", "claude"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_loop_summary() -> None:
    fmt = (STATIC / "format.js").as_uri()
    found = json.loads(
        _node(
            f"import {{ loopSummary }} from '{fmt}';"
            "const one = {agent: 'claude', scope: 'all projects'};"
            "console.log(JSON.stringify([loopSummary([]), loopSummary([one]),"
            " loopSummary([one, {agent: 'codex', scope: 'app'}, {agent: 'claude', scope: 'b'}])]));"
        )
    )
    assert found == [
        "no loop running: run /kengash:loop in your agent",
        "loop running (claude · all projects)",
        "3 loops running (claude, codex)",
    ]


def test_overview_shows_the_loop_and_switches_auto_mode() -> None:
    page = (STATIC / "views" / "overview.js").read_text()
    assert "loopSummary(" in page and "toggle(" in page and "loop_start" in page
    shell = (STATIC / "app.js").read_text()
    assert "30_000" in shell and '"overview"' in shell
