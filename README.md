# beancount-sg

Personal collection of Beancount plugins and Fava extensions.

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
currencies) that have balance assertions, it sets the posting flag to `*` if a later `balance`
directive on that account or one of its parents covers it, and `!` otherwise. The transaction flag
becomes `!` if any such posting is uncovered, else `*`. Other transactions and special flags are
left alone.

## Development

```bash
uv sync            # create .venv and install the package + dev tools
uv run pytest      # run tests
uv run ruff check  # lint
uv run ruff format # format
```
