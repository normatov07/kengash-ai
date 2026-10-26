"""Replace common secrets with [REDACTED] before text reaches the journal or memory."""

import re

MARK = "[REDACTED]"
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
)
_TOKENS = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{10,}"
    r"|sk-[A-Za-z0-9_-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
)
_ASSIGNMENT = re.compile(
    r"(?i)((?:password|passwd|secret|token|(?:api|access|secret|private)[_-]?key)"
    r"""["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)"""
)


def redact(text: str) -> str:
    """Return `text` with private keys, API tokens and secret assignments masked."""
    text = _PRIVATE_KEY.sub(MARK, text)
    text = _TOKENS.sub(MARK, text)
    return _ASSIGNMENT.sub(rf"\1{MARK}", text)
