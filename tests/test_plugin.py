"""Plugin manifests (SP4 spec decision 10)."""

import json
from pathlib import Path

from kengash_ai import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_is_named_kengash() -> None:
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert (plugin["name"], plugin["version"]) == ("kengash", __version__)
    agy = json.loads((ROOT / ".antigravity-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert (agy["name"], agy["version"]) == ("kengash", __version__)
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert market["name"] == "kengash-ai"
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [("kengash", "./")]
