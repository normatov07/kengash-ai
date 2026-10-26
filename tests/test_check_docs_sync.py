import subprocess
from pathlib import Path

import pytest

from scripts.check_docs_sync import main, module_of, problems


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_module_of_maps_package_paths() -> None:
    assert module_of("src/kengash_ai/cli.py") == "cli"
    assert module_of("src/kengash_ai/store/paths.py") == "store"
    assert module_of("src/kengash_ai/__init__.py") is None
    assert module_of("src/kengash_ai/py.typed") is None
    assert module_of("tests/test_cli.py") is None


def test_module_change_without_doc_is_reported() -> None:
    assert problems(["src/kengash_ai/cli.py"]) == [
        "cli: changed without docs/modules/cli/README.md"
    ]


def test_module_change_with_doc_passes() -> None:
    assert problems(["src/kengash_ai/cli.py", "docs/modules/cli/README.md"]) == []


def test_each_module_is_reported_once() -> None:
    changed = ["src/kengash_ai/store/a.py", "src/kengash_ai/store/b.py"]
    assert problems(changed) == ["store: changed without docs/modules/store/README.md"]


def test_base_mode_fails_until_the_doc_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-b", "main")
    write(tmp_path / "README.md", "base\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    git(tmp_path, "switch", "-c", "feature")
    write(tmp_path / "src" / "kengash_ai" / "widget.py", "X = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "add widget")
    monkeypatch.chdir(tmp_path)

    assert main(["--base", "main"]) == 1
    assert capsys.readouterr().out == "widget: changed without docs/modules/widget/README.md\n"

    write(tmp_path / "docs" / "modules" / "widget" / "README.md", "# widget\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "document widget")
    assert main(["--base", "main"]) == 0


def test_staged_mode_checks_the_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git(tmp_path, "init", "-b", "main")
    write(tmp_path / "src" / "kengash_ai" / "widget.py", "X = 1\n")
    git(tmp_path, "add", ".")
    monkeypatch.chdir(tmp_path)
    assert main(["--staged"]) == 1


def test_unknown_base_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git(tmp_path, "init", "-b", "main")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="pass a valid --base"):
        main(["--base", "nope"])
