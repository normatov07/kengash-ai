"""Plugin manifests (SP4 spec decision 10)."""

import json
from pathlib import Path

from super_harness import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_the_plugin_manifest_names_the_package_and_its_version() -> None:
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert (plugin["name"], plugin["version"]) == ("super-harness", __version__)
    agy = json.loads((ROOT / ".antigravity-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert (agy["name"], agy["version"]) == ("super-harness", __version__)
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [("super-harness", "./")]
