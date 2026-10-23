"""The UI's static screens: served without the token, and their template helper escapes
every interpolated value (SP5 spec decision 1)."""

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
