# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

`beancount-sg` is a personal collection of [Beancount](https://github.com/beancount/beancount)
plugins and [Fava](https://github.com/beancount/fava) extensions. "SG" is the author's initials;
the project has nothing to do with Singapore.

It is **not published to PyPI**; users install it from GitHub
(`pip install git+https://github.com/gorlins/beancount-sg.git`). Don't add PyPI publishing steps.

## Layout

- `src/beancount_sg/` — the package (src layout, built with hatchling).
  - Beancount plugins are referenced from a ledger as `plugin "beancount_sg.<module>"`.
  - Fava extensions are referenced as `custom "fava-extension" "beancount_sg.<module>"`.
- `tests/` — pytest tests.
- Fava is an optional dependency (the `fava` extra). Code that imports `fava` must live in
  modules that plugin-only users never import.

## Development

The project uses [uv](https://docs.astral.sh/uv/); `uv.lock` is committed.

```bash
uv sync                    # install package + dev tools into .venv
uv run pytest              # tests
uv run ruff check          # lint
uv run ruff format         # format
```

Before committing, make sure `ruff check`, `ruff format --check`, and `pytest` all pass. If you
change dependencies, update and commit `uv.lock` (CI runs `uv sync --locked`).

Supported Python versions are 3.11 through 3.15, all tested in CI. When adding or dropping a
version, update the CI matrix in `.github/workflows/ci.yml` and the classifiers in
`pyproject.toml` together.

## Versioning and releases

The version is derived from git tags by `hatch-vcs`; never hardcode a version in
`pyproject.toml` or the package. `beancount_sg.__version__` reads it from installed metadata.

- Releases are `vX.Y.Z` tags on `main` (`git tag v0.2.0 && git push origin v0.2.0`). Only create
  or push tags when the user asks.
- Untagged commits get versions like `0.2.1.dev3+g<sha>`.
- CI needs full history (`fetch-depth: 0`) to see tags; keep it.
- `.git_archival.txt` + `.gitattributes` let GitHub tarball installs resolve the version; keep them.

## Git workflow

- **Use semantically meaningful branch names** that describe the change, with a type prefix, e.g.
  `feat/<plugin-name>`, `fix/<what-broke>`, `ci/<change>`, `docs/<topic>`, `build/<change>`.
  Never use auto-generated or random names.
- One logical change per branch and pull request. Start new work from the latest `main`.
- Don't push directly to `main`; open a pull request.
