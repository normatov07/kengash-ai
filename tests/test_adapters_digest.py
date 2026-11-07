"""The failure digest: what a failing check's output is cut down to (SP15 spec §3.2)."""

import time
from pathlib import Path

from kengash_ai.adapters.digest import MAX_CHARS, Digest, excerpt, section

FIXTURES = Path(__file__).parent / "fakes" / "fixtures" / "checks"


def load(name: str, worktree: Path) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8").replace("{worktree}", str(worktree))


def touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")


def digest(output: str, tmp_path: Path, command: str = "flutter test", code: int = 1) -> Digest:
    return excerpt(output, command=command, exit_code=code, cwd=tmp_path, log=tmp_path / "x.out")


def test_a_flutter_assertion_keeps_the_failing_test_and_its_values(tmp_path: Path) -> None:
    d = digest(load("flutter_test_assertion.txt", tmp_path), tmp_path)
    assert "[E]" in d.text
    assert "red: 0.1020" in d.text and "red: 0.9961" in d.text
    assert d.text.splitlines()[-1].endswith("Some tests failed.")
    assert "CaptureDirector skip accepted" not in d.text
    assert d.headline.startswith("`flutter test` exit 1: ")


def test_a_compile_error_names_its_file_and_line(tmp_path: Path) -> None:
    touch(tmp_path, "lib/domain/ai/ai_engine.dart")
    d = digest(load("flutter_test_compile.txt", tmp_path), tmp_path)
    assert (d.file, d.line) == ("lib/domain/ai/ai_engine.dart", 53)
    assert "scoreGuess" in d.text


def test_analyzer_rows_survive_and_pub_noise_goes(tmp_path: Path) -> None:
    touch(tmp_path, "lib/core/theme/samurai_theme.dart")
    d = digest(load("flutter_analyze.txt", tmp_path), tmp_path, command="flutter analyze")
    assert "prefer_const_constructors" in d.text and "unnecessary_import" in d.text
    assert "2 issues found" in d.text
    assert "available)" not in d.text
    assert (d.file, d.line) == ("lib/core/theme/samurai_theme.dart", 55)
    assert d.headline.startswith("`flutter analyze` exit 1: ")


def test_pytest_failures_are_kept(tmp_path: Path) -> None:
    touch(tmp_path, "tests/test_retry.py")
    d = digest(load("pytest_failure.txt", tmp_path), tmp_path, command="uv run pytest -q")
    assert "E       assert 2 == 3" in d.text and "1 failed, 40 passed" in d.text
    assert (d.file, d.line) == ("tests/test_retry.py", 12)
    assert "def test_retry():" in d.text


def test_without_markers_the_last_30_lines_stay(tmp_path: Path) -> None:
    output = "\n".join(f"line {n}" for n in range(1, 101))
    d = digest(output, tmp_path, command="make check", code=3)
    assert d.text.splitlines() == [f"line {n}" for n in range(71, 101)]
    assert d.headline == "`make check` exit 3: line 100"


def test_the_digest_is_capped_and_says_where_the_rest_is(tmp_path: Path) -> None:
    output = "\n".join(f"error: {n}" for n in range(500))
    d = digest(output, tmp_path)
    lines = d.text.splitlines()
    assert len(lines) == 60 and len(d.text) <= MAX_CHARS + 100
    assert lines[0] == "error: 0"
    assert lines[-3] == f"… 441 more lines; full output: {tmp_path / 'x.out'}"
    assert lines[-2:] == ["error: 498", "error: 499"]


def test_huge_output_is_fast(tmp_path: Path) -> None:
    lines = [f"ok {n}" for n in range(200_000)]
    lines[100_000] = "error: boom"
    began = time.perf_counter()
    d = digest("\n".join(lines), tmp_path)
    assert time.perf_counter() - began < 3.0  # 0.5 s alone; the bound tolerates a busy machine
    assert "error: boom" in d.text


def test_ansi_codes_and_long_lines_are_cleaned(tmp_path: Path) -> None:
    d = digest("\x1b[31merror: red\x1b[0m\nerror: " + "x" * 1000, tmp_path)
    first, second = d.text.splitlines()[:2]
    assert first == "error: red"
    assert len(second) == 300


def test_paths_outside_the_worktree_are_not_locations(tmp_path: Path) -> None:
    d = digest("/usr/lib/x.py:3: error: nope", tmp_path)
    assert (d.file, d.line) == ("", 0)


def test_section_fences_the_digest(tmp_path: Path) -> None:
    d = digest("error: one\n```\nerror: two", tmp_path)
    assert section(d) == f"{d.headline}\n```text\nerror: one\n ```\nerror: two\n```"


def test_a_passing_test_named_after_an_error_is_not_a_marker(tmp_path: Path) -> None:
    # review finding: flutter repeats each test's name on its progress line
    renamed = load("flutter_test_assertion.txt", tmp_path).replace(
        "HallCamera equality and hashCode match over camera properties",
        "shows an error banner when the engine fails",
    )
    d = digest(renamed, tmp_path)
    assert "shows an error banner" not in d.text and "shows an error banner" not in d.headline
    assert "[E]" in d.text and "red: 0.9961" in d.text


def test_the_headline_prefers_a_strong_marker(tmp_path: Path) -> None:
    output = "warming the cache: expected 3 entries\nsetup ok\nFAILED tests/test_a.py::test_x"
    assert digest(output, tmp_path, command="pytest").headline == (
        "`pytest` exit 1: FAILED tests/test_a.py::test_x"
    )


def test_long_lines_stay_fast(tmp_path: Path) -> None:
    name = "very_long_widget_test_name_" * 4
    lines = [
        f"00:{n % 60:02d} +{n}: {tmp_path}/test/ui/screens/{name}{n}.dart: Widget renders {name}"
        for n in range(100_000)
    ]
    lines += ["Expected: 1", "  Actual: 2", "Some tests failed."]
    began = time.perf_counter()
    d = digest("\n".join(lines), tmp_path)
    assert time.perf_counter() - began < 3.0
    assert "Actual: 2" in d.text
