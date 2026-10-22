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
        ("DB_PASSWORD=hunter2", f"DB_PASSWORD={MARK}"),
        ("export GITHUB_TOKEN=abc123", f"export GITHUB_TOKEN={MARK}"),
        ("SECRET_KEY=django-insecure-xyz", f"SECRET_KEY={MARK}"),
        ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG", f"AWS_SECRET_ACCESS_KEY={MARK}"),
        ('{"api_key": "abc123"}', f'{{"api_key": {MARK}}}'),
        ('password: "two words"', f"password: {MARK}"),
    ],
)
def test_assignments_keep_the_name(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_private_keys_are_redacted() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    assert redact(f"key:\n{pem}\nend") == f"key:\n{MARK}\nend"


@pytest.mark.parametrize(
    "text",
    [
        "token budget is 250000; skip the secret-santa tokens list",
        "max_tokens: 4096",
        "tokens.per_ticket_max: 250000",
        "primary_key: id",
    ],
)
def test_ordinary_text_is_untouched(text: str) -> None:
    assert redact(text) == text
