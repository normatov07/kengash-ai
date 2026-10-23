from pathlib import Path

from conftest import FakeClis
from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.store import StorePaths

runner = CliRunner()


def test_init_then_doctor(store_paths: StorePaths, repo: Path) -> None:
    target = store_paths.project("payments-api").root
    first = runner.invoke(app, ["init", str(repo)])
    assert (first.exit_code, first.stdout) == (
        0,
        f"initialized payments-api: {repo / '.harness'} -> {target}\n",
    )
    second = runner.invoke(app, ["init", str(repo)])
    assert second.stdout == "ok payments-api: already initialized\n"
    doctor = runner.invoke(app, ["doctor"])
    assert (doctor.exit_code, doctor.stdout) == (0, "ok: 1 project\n")
    assert runner.invoke(app, ["doctor", "--quiet"]).stdout == ""


def test_doctor_exit_code_signals_problems(store_paths: StorePaths, repo: Path) -> None:
    runner.invoke(app, ["init", str(repo)])
    (repo / ".harness").unlink()
    result = runner.invoke(app, ["doctor"])
    assert (result.exit_code, result.stdout) == (
        1,
        "payments-api: link missing; run: harness doctor --fix\n",
    )
    fixed = runner.invoke(app, ["doctor", "--fix"])
    assert (fixed.exit_code, fixed.stdout) == (0, "payments-api: link missing; repaired\n")


def test_errors_go_to_stderr_with_spec_exit_codes(store_paths: StorePaths, repo: Path) -> None:
    (repo / ".harness").mkdir()
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 4
    assert result.stderr == f"{repo / '.harness'} is a real folder; run: harness adopt {repo}\n"


def test_link_and_adopt(store_paths: StorePaths, repo: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(repo)])
    moved = repo.with_name("payments")
    repo.rename(moved)
    linked = runner.invoke(app, ["link", "payments-api", str(moved)])
    target = store_paths.project("payments-api").root
    assert linked.stdout == f"linked payments-api: {moved / '.harness'} -> {target}\n"
    legacy = tmp_path / "legacy"
    (legacy / ".harness").mkdir(parents=True)
    adopted = runner.invoke(app, ["adopt", str(legacy)])
    assert adopted.exit_code == 0
    assert adopted.stdout.startswith("adopted legacy: 0 new, 0 conflicts; original kept in ")


def test_json_output(store_paths: StorePaths, repo: Path) -> None:
    result = runner.invoke(app, ["init", str(repo), "--json"])
    assert '"slug": "payments-api"' in result.stdout


def test_doctor_warnings_do_not_fail(store_paths: StorePaths, repo: Path) -> None:
    runner.invoke(app, ["init", str(repo)])
    (repo / ".mcp.json").write_text("{}")
    result = runner.invoke(app, ["doctor"])
    assert (result.exit_code, result.stdout) == (
        0,
        "payments-api: warning: repo ships .mcp.json; workers run them without a trust prompt\n",
    )
    assert runner.invoke(app, ["doctor"]).stdout == "ok: 1 project\n"


def test_doctor_fails_on_a_blocking_provider(
    store_paths: StorePaths, repo: Path, fake_clis: FakeClis
) -> None:
    runner.invoke(app, ["init", str(repo)])
    fake_clis.hide("codex")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1 and result.stdout.startswith("codex: not installed;")
