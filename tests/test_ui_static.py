"""The UI's static screens: served without the token, and their template helper escapes
every interpolated value (SP5 spec decision 1)."""

import json
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
