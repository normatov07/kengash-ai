"""Worker environments: subscription logins only, no conductor markers (system spec §10)."""

from collections.abc import Mapping

API_KEYS: dict[str, tuple[str, ...]] = {
    "claude": ("ANTHROPIC_API_KEY",),
    "codex": ("OPENAI_API_KEY", "CODEX_API_KEY"),
    "antigravity": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}
CONDUCTOR_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def worker_env(
    environ: Mapping[str, str], provider: str, role: str, *, allow_api_key: bool
) -> dict[str, str]:
    """`environ` without API keys (except the provider's own when allowed) or conductor markers."""
    kept = set(API_KEYS.get(provider, ())) if allow_api_key else set()
    dropped = {key for keys in API_KEYS.values() for key in keys} - kept
    dropped.update(CONDUCTOR_MARKERS)
    env = {key: value for key, value in environ.items() if key not in dropped}
    env["KENGASH_AGENT"] = role
    return env
