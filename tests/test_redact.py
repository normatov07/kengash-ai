import pytest

from super_harness.store.redact import MARK, redact


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-" + "a" * 24,
        "sk-" + "b" * 32,
        "ghp_" + "c" * 36,
        "github_pat_" + "d" * 40,
        "AKIA" + "E" * 16,
        "xoxb-" + "1" * 24,
    ],
)
def test_tokens_are_redacted(secret: str) -> None:
    assert redact(f"use {secret} now") == f"use {MARK} now"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("password = hunter2", f"password = {MARK}"),
        ("API_KEY: abc123def", f"API_KEY: {MARK}"),
        ("db secret=xyz; next", f"db secret={MARK}; next"),
    ],
)
def test_assignments_keep_the_name(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_private_keys_are_redacted() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    assert redact(f"key:\n{pem}\nend") == f"key:\n{MARK}\nend"


def test_ordinary_text_is_untouched() -> None:
    text = "token budget is 250000; skip the secret-santa tokens list"
    assert redact(text) == text
