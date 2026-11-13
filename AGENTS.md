# AGENTS.md

- "SG" in the name is the author's initials, not Singapore.
- Installed from GitHub only; never add PyPI publishing.
- Beancount plugins go in `beancount_sg.plugins`; Fava extensions go in `beancount_sg.ext`.
- Code importing `fava` must stay out of modules that plugin-only users import (fava is an optional extra).
- Never hardcode a version; only create or push release tags when asked.
- Before committing, `ruff check`, `ruff format --check` and `pytest` must pass.
- Branch names describe the change with a type prefix (`feat/…`, `fix/…`, `ci/…`, `docs/…`, `build/…`); never auto-generated names.
- One logical change per branch and PR, started from the latest `main`; never push directly to `main`.
