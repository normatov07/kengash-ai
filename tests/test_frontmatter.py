import pytest

from kengash_ai.model import PLAN_SECTIONS, TICKET_SECTIONS, UserError
from kengash_ai.store.frontmatter import parse, read_sections, render

NAMES = TICKET_SECTIONS
EMPTY = dict.fromkeys(NAMES, "")


def test_round_trip_keeps_meta_and_sections() -> None:
    meta = {"id": "7b55e0c1", "depends_on": ["a91b3d07"], "loop": 2}
    sections = EMPTY | {"Scope": "Rotate keys.\n\nWith overlap.", "Log": "- 09:41 plan"}
    assert parse(render(meta, sections, NAMES), NAMES) == (meta, sections)


def test_render_keeps_key_order_and_flow_lists() -> None:
    meta = {"id": "7b55e0c1", "depends_on": ["a91b3d07"], "branch": "hrn/7b55e0c1"}
    text = render(meta, {}, NAMES)
    assert text.startswith("---\nid: 7b55e0c1\ndepends_on: [a91b3d07]\nbranch: hrn/7b55e0c1\n---\n")


def test_unknown_headings_stay_inside_a_section() -> None:
    sections = EMPTY | {"Scope": "## Background\nkept as text"}
    assert parse(render({}, sections, NAMES), NAMES)[1]["Scope"] == "## Background\nkept as text"


def test_known_headings_inside_content_are_escaped() -> None:
    tricky = "line\n## Log\n\\## Log"
    text = render({}, EMPTY | {"Scope": tricky}, NAMES)
    assert "\n\\## Log\n" in text
    assert parse(text, NAMES)[1]["Scope"] == tricky


def test_unknown_section_names_are_refused() -> None:
    with pytest.raises(UserError, match="unknown sections: Notes"):
        render({}, {"Notes": "x"}, NAMES)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no frontmatter", "no frontmatter"),
        ("---\nid: x\n", "not closed"),
        ("---\n- a\n---\n", "not a mapping"),
        ("---\nid: [unclosed\n---\n", "invalid YAML"),
    ],
)
def test_bad_frontmatter_is_a_user_error(text: str, message: str) -> None:
    with pytest.raises(UserError, match=message):
        parse(text, NAMES)


def test_read_sections_takes_known_headings_outside_fences() -> None:
    text = "\n## Goal\nShip it.\n\n## Scope\nKeys only.\n```md\n## Goal\n```\n"
    assert read_sections(text, PLAN_SECTIONS) == {
        "Goal": "Ship it.",
        "Scope": "Keys only.\n```md\n## Goal\n```",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("## Goals\nx", "unknown section 'Goals'"),
        ("## Goal\nx\n## Goal\ny", "section 'Goal' appears twice"),
        ("intro\n## Goal\nx", "text before the first ## heading"),
    ],
)
def test_read_sections_refuses_bad_input(text: str, message: str) -> None:
    with pytest.raises(UserError, match=message):
        read_sections(text, PLAN_SECTIONS)
