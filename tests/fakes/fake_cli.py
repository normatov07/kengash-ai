"""Fake claude, codex and agy for tests: `fake_cli.py <cli> <args...>`.

State lives in $HARNESS_FAKE_DIR/<cli>/: `queue/NNNN.json` replies (lowest first),
`calls.jsonl`, a `signed_out` flag and claude's optional `auth_method` file. Status
commands answer from that state; every other call pops the next queued reply, which may
write `edits`, run a `shell` command and `sleep` before printing its stdout.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
WATCHED = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "CLAUDECODE",
    "BROWSER",
    "CLAUDE_CODE_ENTRYPOINT",
    "KENGASH_AGENT",
)
VERSIONS = {"claude": "2.1.309 (Claude Code)", "codex": "codex-cli 0.161.0", "agy": "1.4.5"}
NO_REPLY = 97


def _status(cli: str, args: list[str], state: Path) -> tuple[str, int] | None:
    """The answer to a version or sign-in check, or None for any other call."""
    if args == ["--version"]:
        return VERSIONS[cli] + "\n", 0
    signed_out = (state / "signed_out").exists()
    if cli == "claude" and args[:2] == ["auth", "status"]:
        if signed_out:
            return json.dumps({"loggedIn": False}) + "\n", 1
        method_file = state / "auth_method"
        method = method_file.read_text().strip() if method_file.exists() else "claude.ai"
        reply = {"loggedIn": True, "authMethod": method, "apiProvider": "firstParty"}
        return json.dumps(reply) + "\n", 0
    if cli == "codex" and args[:2] == ["login", "status"]:
        return ("Not logged in\n", 1) if signed_out else ("Logged in using ChatGPT\n", 0)
    if cli == "agy" and args[:1] == ["models"]:
        return ("not signed in\n", 1) if signed_out else ("gemini-3-pro\n", 0)
    return None


def main(cli: str, args: list[str]) -> int:
    state = Path(os.environ["HARNESS_FAKE_DIR"]) / cli
    state.mkdir(parents=True, exist_ok=True)
    status = _status(cli, args, state)
    if status is not None:  # version and sign-in checks are answered, not recorded
        sys.stdout.write(status[0])
        return status[1]
    call = {
        "argv": args,
        "cwd": os.getcwd(),
        "env": {name: os.environ[name] for name in WATCHED if name in os.environ},
    }
    with (state / "calls.jsonl").open("a", encoding="utf-8") as calls:
        calls.write(json.dumps(call) + "\n")
    reply = _take(sorted((state / "queue").glob("*.json")))
    if reply is None:
        sys.stderr.write(f"fake {cli}: no reply queued\n")
        return NO_REPLY
    for name, content in reply.get("edits", {}).items():
        target = Path.cwd() / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if reply.get("shell"):  # e.g. an agent that commits, or a user acting mid-step
        subprocess.run(["sh", "-c", reply["shell"]], capture_output=True, check=False)
    time.sleep(reply.get("sleep", 0))
    fixture = reply.get("fixture")
    stdout = (FIXTURES / fixture).read_text(encoding="utf-8") if fixture else reply["stdout"]
    sys.stdout.write(stdout)
    sys.stderr.write(reply.get("stderr", ""))
    return int(reply.get("exit", 0))


def _take(queued: list[Path]) -> dict[str, Any] | None:
    """The first queued reply, claimed by an atomic rename: parallel workers never get the
    same one (SP13)."""
    for path in queued:
        taken = path.with_suffix(f".{os.getpid()}.taken")
        try:
            path.rename(taken)
        except FileNotFoundError:
            continue  # another worker took it
        reply: dict[str, Any] = json.loads(taken.read_text(encoding="utf-8"))
        taken.unlink()
        return reply
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
