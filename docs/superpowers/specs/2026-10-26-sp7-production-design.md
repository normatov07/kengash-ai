# SP7: Production readiness (design)

Date: 2026-10-26. Status: written under the user's instruction "make the app production ready" (2026-10-26) without design questions; calls marked *call* are open to veto.

## 1. Why

An audit on 2026-10-26 found the features complete but the product not yet fit to publish or to run for months:

- **Speed.** A store with 1,500 tickets and 30,000 journal events takes 24 s to draw the Overview, 18 s the board, 5 s Memory and 2 s a ticket. Profiles: `settings.load` re-parses three YAML layers once per ticket (about 70% of the time), and every ticket's frontmatter goes through ruamel's pure-Python parser on every request (about 3 ms each); the Overview loads every ticket twice.
- **Packaging.** The sdist ships `.claude/` (263 files, local agent settings and an old worktree), `.superpowers/` and `.import_linter_cache/`. Metadata has no classifiers, keywords or project URLs. There is no release workflow; the name `super-harness` is free on PyPI.
- **Security hardening.** The UI already checks Host, Origin, a constant-time token, `SameSite=Strict` `HttpOnly` cookies and an `X-Harness` header on POSTs, but sends no CSP, `nosniff`, framing or referrer headers, although the first request carries the token in its URL. No security policy file; ruff's security rules are off.
- **Operations.** Worker logs (`runtime/logs/*.out|log`, raw CLI output) are never removed. Native Windows fails late instead of saying so (WSL is the supported path, system spec §1).
- **Project hygiene.** No CHANGELOG, CONTRIBUTING, SECURITY, code of conduct, issue templates or dependency updates; CI runs one job without Python 3.13, packaging checks or a vulnerability audit; macOS CI was red until `fix/ci-macos-ui-race`.

## 2. Goals, non-goals, anti-goals

- Goals: the UI answers in under 1 s warm on the store above; `uv build` artifacts contain exactly the product; a tagged release publishes to PyPI with attestations through a reviewed workflow; CI covers Linux and macOS on 3.12–3.14 plus packaging and an audit; users and contributors find install, configuration, security and release docs.
- Non-goals: native Windows support; a database or index; telemetry; publishing on the user's behalf (PyPI trusted-publisher setup and tags stay the user's actions).
- Anti-goals: a cache that can show stale settings or tickets after a change; a CSP that breaks a screen; a dependency bot that rewrites `pyproject.toml` bounds.

## 3. Decisions

1. **Stat-keyed parse caches.** Settings layers, resolved settings and plan/ticket documents are cached per process keyed by each file's `(path, st_mtime_ns, st_size, st_ino)`; harness writes atomically (new inode), so any change misses the cache. Cached values are copied on read, so callers can never mutate them. The caches are bounded (LRU, 4,096 documents) and thread-safe for the UI's thread pool.
2. **Faster YAML where available.** `load_yaml` reuses one safe loader per thread and uses ruamel's C extension when it is installed; `ruamel.yaml.clib` becomes a dependency on CPython. PyYAML is not used: it reads YAML 1.1, where `on`/`off` turn into booleans and break `agents.<role>.on`. *call*
3. **One ticket scan per view.** The Overview reuses one scan of the store.
4. **Security headers** on every UI response: `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'` (inline style attributes are part of the screens' markup; scripts stay `'self'` only), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
5. **Ruff security rules (`S`)** are on. `S603`/`S607` are ignored with a stated reason: harness launches the official CLIs and git by name from PATH by design (system spec hard rule 6), always with argument lists, never a shell string. Tests may assert.
6. **Native Windows** stops at the CLI entry with exit 4: "harness runs on Linux and macOS; on Windows use WSL".
7. **Log retention.** `logs.keep_days` (default 30; 0 keeps everything) in SETTINGS.md; each worker start removes `runtime/logs` files untouched for longer, and `harness doctor --fix` does the same. *call*
8. **Packaging.** An explicit sdist include list (`src`, `skills`, `tests`, `docs`, `evals`, `scripts`, top-level project files); `.gitignore` covers local agent and tool folders; classifiers, keywords and URLs in `pyproject.toml`; `scripts/check_dist.py` fails a build that misses product files or carries forbidden ones, and CI installs the built wheel into a clean environment and runs it.
9. **Release workflow** on a `v*` tag: check that the tag matches the package version, build, `check_dist`, publish with `pypa/gh-action-pypi-publish` through PyPI trusted publishing (attestations on by default) from a `pypi` environment, then a GitHub release with the artifacts. Actions are pinned by commit; permissions are per job.
10. **CI**: Python 3.12, 3.13 and 3.14 on ubuntu and macOS; a package job (build, check, clean install, smoke); a `pip-audit` job over the locked dependencies; one run per ref at a time; job timeouts.
11. **Dependabot** for GitHub Actions and uv, weekly and grouped, `versioning-strategy: lockfile-only` so `pyproject.toml` bounds never move.
12. **Community and docs**: README (requirements, install, quickstart, commands, configuration, custom agents, security model, troubleshooting, uninstall), CHANGELOG (Keep a Changelog), CONTRIBUTING, SECURITY (private reporting through GitHub advisories, scope), a short code of conduct pointing to Contributor Covenant 2.1, issue and PR templates, `docs/releasing.md`.
13. **SP6 deferred minors**: `agent_config` reads settings inside `settings.lock`; a custom step's board column sits where its first workflow runs it.
14. **Accessibility**: an axe-core scan of the seven screens; serious and critical violations fixed.

## 4. Acceptance (SP7 exit)

- [ ] On the 1,500-ticket store every view answers warm in under 1 s; a change to SETTINGS.md or a ticket shows on the next request (cache tests).
- [ ] `uv build` artifacts pass `scripts/check_dist.py`; a clean venv install runs `harness --version` and imports the UI.
- [ ] UI responses carry the §3.4 headers and every screen renders under the CSP in Chrome with no console violations.
- [ ] `ruff` with `S` is clean; native Windows exits 4 with the WSL message; log retention prunes old files only.
- [ ] CI green on ubuntu and macOS for 3.12, 3.13, 3.14, plus package and audit jobs; release workflow and Dependabot config reviewed.
- [ ] README, CHANGELOG, CONTRIBUTING, SECURITY, code of conduct, templates and `docs/releasing.md` exist; `make check` green.
- [ ] axe-core reports no serious or critical violations on the seven screens.
