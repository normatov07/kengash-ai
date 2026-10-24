"""Markdown documents with YAML frontmatter and `## ` sections (system spec §4.4).

A content line that would read as a known heading is written with one extra leading
backslash and restored on read, so a verbatim prompt can never split a document.
"""

from collections.abc import Container, Sequence
from typing import Any

from super_harness.model import UserError
from super_harness.store.yamlio import dump_yaml, load_yaml

FENCE = "---\n"


def parse(text: str, names: Sequence[str]) -> tuple[dict[str, Any], dict[str, str]]:
    """Split a document into its frontmatter mapping and its known sections."""
    meta, body = split_frontmatter(text)
    return meta, _split(body, names)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """The frontmatter mapping and the text after it (skills and documents alike)."""
    if not text.startswith(FENCE):
        raise UserError("document has no frontmatter")
    end = text.find("\n" + FENCE, len(FENCE) - 1)
    if end < 0:
        raise UserError("frontmatter is not closed with ---")
    meta = load_yaml(text[len(FENCE) : end + 1], "frontmatter") or {}
    if not isinstance(meta, dict):
        raise UserError("frontmatter is not a mapping")
    return meta, text[end + 1 + len(FENCE) :]


def render(meta: dict[str, Any], sections: dict[str, str], names: Sequence[str]) -> str:
    """Write the frontmatter, then every known section in order; empty ones as bare headings."""
    unknown = sorted(set(sections) - set(names))
    if unknown:
        raise UserError(f"unknown sections: {', '.join(unknown)}")
    parts = [FENCE, dump_yaml(meta) if meta else "", FENCE]
    for name in names:
        parts.append(f"\n## {name}\n")
        text = sections.get(name, "").strip("\n")
        if text:
            parts.append(_escape(text, names) + "\n")
    return "".join(parts)


def read_sections(text: str, names: Sequence[str]) -> dict[str, str]:
    """Parse `## Name` sections typed by an agent; unknown, repeated or stray text is an error.

    Lines inside ``` fences are content, so a Markdown example cannot open a section.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        if line.startswith("## ") and not fenced:
            name = line[3:].strip()
            if name not in names:
                known = ", ".join(names)
                raise UserError(f"unknown section {name!r}; use {known} (### for sub-headings)")
            if current is not None:
                sections[current] = "\n".join(lines).strip("\n")
            if name in sections:
                raise UserError(f"section {name!r} appears twice")
            current, lines = name, []
        elif current is not None:
            lines.append(line)
        elif line.strip():
            raise UserError("text before the first ## heading")
    if current is not None:
        sections[current] = "\n".join(lines).strip("\n")
    return sections


def _split(body: str, names: Sequence[str]) -> dict[str, str]:
    headings = {f"## {name}": name for name in names}
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in body.split("\n"):
        if line in headings:
            if current is not None:
                sections[current] = _unescape(lines, headings)
            current, lines = headings[line], []
        elif current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = _unescape(lines, headings)
    return sections


def _heading_like(line: str, headings: Container[str]) -> bool:
    return line.lstrip("\\") in headings


def _escape(text: str, names: Sequence[str]) -> str:
    headings = {f"## {name}" for name in names}
    return "\n".join(
        "\\" + line if _heading_like(line, headings) else line for line in text.split("\n")
    )


def _unescape(lines: list[str], headings: Container[str]) -> str:
    restored = [
        line[1:] if line.startswith("\\") and _heading_like(line, headings) else line
        for line in lines
    ]
    return "\n".join(restored).strip("\n")
