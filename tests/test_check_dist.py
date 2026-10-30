"""scripts/check_dist.py: built artifacts hold the product and nothing local (SP7 §3.8)."""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import check_dist

WHEEL = [
    "kengash_ai/__init__.py",
    "kengash_ai/ui/static/fonts/inter.woff2",
    "kengash_ai/skills/loop/SKILL.md",
    "kengash_ai/store/defaults/SETTINGS.md",
    "kengash_ai/ui/static/index.html",
    "kengash_ai/roles/plan/SKILL.md",
    "kengash_ai-0.1.0.dist-info/METADATA",
]
SDIST = ["src/kengash_ai/__init__.py", "skills/loop/SKILL.md", "LICENSE", "pyproject.toml"]


def build(folder: Path, wheel: list[str], sdist: list[str]) -> Path:
    folder.mkdir()
    with zipfile.ZipFile(folder / "kengash_ai-0.1.0-py3-none-any.whl", "w") as archive:
        for name in wheel:
            archive.writestr(name, "x")
    with tarfile.open(folder / "kengash_ai-0.1.0.tar.gz", "w:gz") as archive:
        for name in sdist:
            info = tarfile.TarInfo(f"kengash_ai-0.1.0/{name}")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
    return folder


def test_good_artifacts_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert check_dist.main([str(build(tmp_path / "dist", WHEEL, SDIST))]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("wheel", "sdist", "problem"),
    [
        (WHEEL[1:2] + WHEEL[2:], SDIST, "wheel lacks kengash_ai/__init__.py"),
        (
            [n for n in WHEEL if "fonts" not in n],
            SDIST,
            "wheel lacks kengash_ai/ui/static/fonts",
        ),
        (WHEEL, [n for n in SDIST if n != "LICENSE"], "sdist lacks LICENSE"),
        (WHEEL, [*SDIST, ".claude/settings.local.json"], "sdist ships .claude/"),
        (WHEEL, [*SDIST, "full prompt of app.md"], "sdist ships full prompt of app.md"),
        ([*WHEEL, "kengash_ai/__pycache__/x.pyc"], SDIST, "wheel ships __pycache__/"),
    ],
)
def test_bad_artifacts_name_the_problem(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    wheel: list[str],
    sdist: list[str],
    problem: str,
) -> None:
    assert check_dist.main([str(build(tmp_path / "dist", wheel, sdist))]) == 1
    assert problem in capsys.readouterr().out


def test_a_missing_artifact_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "dist").mkdir()
    assert check_dist.main([str(tmp_path / "dist")]) == 1
    assert "no wheel" in capsys.readouterr().out
