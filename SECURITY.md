# Security policy

## Supported versions

Security fixes go into the latest release. Upgrade with `uv tool upgrade kengash-ai`.

## Reporting a vulnerability

Please report it privately through GitHub: on this repository's **Security** tab, choose **Report a vulnerability** (a private security advisory). Do not open a public issue.

Include what you found, how to reproduce it, which version and platform you used, and what an attacker gains. We aim to answer within 7 days and to ship a fix, or a plan for one, within 30 days, and we credit reporters who want it.

## Scope

In scope:

- The `harness` CLI, its workers and the store at `~/.harness`.
- The local web UI: its token, Host, Origin and header checks, and anything that lets another site or local user act through it.
- Leaks of provider credentials, API keys or the UI token through logs, the journal, memory files or prompts.
- The installed skills and role skills, where they could lead an agent to unsafe actions.

Out of scope: weaknesses in the agent CLIs themselves (report those to their vendors), and attacks that need control of your user account already.

## How harness protects you

Providers run only through their official binaries under your login; harness never reads or reuses OAuth tokens and removes provider API-key variables from worker environments. The UI listens on 127.0.0.1 only and sends a strict Content Security Policy. See the README's security model for the rest.
