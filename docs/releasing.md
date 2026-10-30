# Releasing

How a version of Kengash AI reaches PyPI and GitHub. The workflow is `.github/workflows/release.yml`; a pushed tag `vX.Y.Z` runs it.

## One-time setup (a maintainer, in the browser)

1. **PyPI trusted publisher.** On pypi.org, under your account's Publishing settings, add a pending trusted publisher: project `kengash-ai`, owner `normatov07`, repository `kengash-ai`, workflow `release.yml`, environment `pypi`. No API token is created or stored; PyPI trusts this workflow's OIDC identity, and the publish action uploads attestations for each file.
2. **GitHub environment.** In the repository settings, create the environment `pypi` and limit it to tags matching `v*`, so only a version tag can publish. Where the plan offers required reviewers (public repositories, or paid plans for private ones), add yourself so every publish waits for an approval click.
3. **Branch protection.** Protect `main`: require pull requests and the `ci` checks (every `check` job, `package`, `audit`).
4. **Private vulnerability reporting.** Turn it on under Security → Settings, as SECURITY.md promises.

## Each release

1. On a branch, set `__version__` in `src/kengash_ai/__init__.py` (Semantic Versioning: a fix bumps the patch, a feature the minor, a breaking change the major; before 1.0.0 a breaking change bumps the minor). The plugin manifests in `.claude-plugin/` and `.antigravity-plugin/` carry the same version.
2. In CHANGELOG.md, rename the top section to the version and today's date, `## [X.Y.Z] - YYYY-MM-DD`, and add its link at the bottom.
3. Run `make check`, `make dist` and `make audit`; open a pull request; merge it when CI is green.
4. Tag the merge commit and push the tag:

        git checkout main && git pull
        git tag -a vX.Y.Z -m "vX.Y.Z"
        git push origin vX.Y.Z

5. Approve the `pypi` environment when the workflow asks. The workflow checks the tag against `__version__`, builds, runs `scripts/check_dist.py`, publishes to PyPI, then creates the GitHub release with the artifacts and the version's CHANGELOG section.
6. Check it: `uv tool install --force 'kengash-ai[ui]==X.Y.Z'` and `kengash --version`.

## If something goes wrong

- **The tag does not match the version:** delete the tag (`git push --delete origin vX.Y.Z`), fix the version in a pull request, and tag again.
- **PyPI refuses the upload:** a version can be uploaded once; bump the patch version and release again. Never reuse a version number.
- **A bad release is out:** yank it on PyPI (installs that name it keep working, new ones skip it), fix forward, and say so in the CHANGELOG.
