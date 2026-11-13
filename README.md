# beancount-sg

Personal collection of Beancount plugins and Fava extensions. ("SG" is the author's initials.)

## Installation

This package is not published on PyPI; install it directly from GitHub:

```bash
pip install git+https://github.com/gorlins/beancount-sg.git
```

To use the Fava extensions, install with the `fava` extra:

```bash
pip install "beancount-sg[fava] @ git+https://github.com/gorlins/beancount-sg.git"
```

Pin to a tag, branch, or commit by appending `@<ref>`, e.g.
`git+https://github.com/gorlins/beancount-sg.git@v0.1.0`.

With uv:

```bash
uv add git+https://github.com/gorlins/beancount-sg.git
```

## Plugins

Beancount plugins live in `beancount_sg.plugins`; Fava extensions live in `beancount_sg.ext`.

### `beancount_sg.plugins.flag_balanced`

```beancount
plugin "beancount_sg.plugins.flag_balanced"
```

Marks which transactions are verified by a balance assertion. For postings to accounts (and
currencies) that have their own `balance` assertions, it sets the posting flag to `*` if a later
assertion on that exact account covers it, and `!` otherwise. Other postings keep their flags,
e.g. ones set by other plugins.

The transaction flag is then derived from all posting flags: `!` if any posting is `!`, else `*`
if any posting is `*`. Special transaction flags (e.g. `P`) are kept. List this plugin after any
plugins that set posting flags.

## Development

```bash
uv sync            # create .venv and install the package + dev tools
uv run pytest      # run tests
uv run ruff check  # lint
uv run ruff format # format
```

Before committing, make sure `ruff check`, `ruff format --check` and `pytest` all pass; CI runs
them on every supported Python version.

Fava is an optional dependency (the `fava` extra), so code that imports `fava` must stay out of
modules that plugin-only users import.

### Branches and pull requests

- Name branches after the change, with a type prefix: `feat/…`, `fix/…`, `ci/…`, `docs/…`,
  `build/…`.
- One logical change per branch and pull request, started from the latest `main`.
- Don't push directly to `main`.

### Releases

The version is derived from git tags, so it is never written in the code. To release, tag `main`
and push the tag:

```bash
git tag v0.2.0
git push origin v0.2.0
```
