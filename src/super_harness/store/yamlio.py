"""YAML in and out: safe loading, readable round-trip dumping."""

import threading
from io import StringIO
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from super_harness.model import UserError

_local = threading.local()


def _safe() -> YAML:
    """This thread's safe loader: YAML 1.2, C-accelerated when ruamel.yaml.clib is there."""
    loader: YAML | None = getattr(_local, "yaml", None)
    if loader is None:
        loader = _local.yaml = YAML(typ="safe", pure=False)
    return loader


def load_yaml(text: str, source: str) -> Any:
    """Parse YAML with the safe loader; errors become a UserError naming `source`."""
    try:
        return _safe().load(text)
    except YAMLError as exc:
        problem = getattr(exc, "problem", None) or type(exc).__name__
        raise UserError(f"{source}: invalid YAML: {problem}") from exc


def dump_yaml(data: Any) -> str:
    """Block style for mappings, flow style for leaf lists and maps, key order kept."""
    yaml = YAML()
    yaml.default_flow_style = None
    yaml.width = 4096
    buffer = StringIO()
    yaml.dump(data, buffer)
    return buffer.getvalue()
