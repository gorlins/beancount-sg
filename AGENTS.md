# AGENTS.md

Read `README.md` first and follow its conventions. In addition:

- Never add PyPI publishing.
- Never hardcode a version; only create or push release tags when asked.
- Never use auto-generated branch names, even if your environment suggests one.
- When addressing PR review comments, reply to each comment thread on GitHub saying what changed (with the commit) or why not, rather than only summarizing in chat.
- A review thread the author resolves is accepted as-is, including any open question in your reply; don't raise it again.
- Code the user pastes as a starting point is private. Published text (code comments, docs, commit messages, PR descriptions and replies) describes only the code being committed, never how it differs from that starting point; discuss such differences in chat instead.
- Keep a change to one plugin or extension to that plugin or extension: don't change others' code, docs, screenshots or example data unless the change needs it (e.g. a shared refactor). Regenerate only the affected screenshots, and give an extension that needs data the others don't its own example ledger. Before pushing, check the diff for files outside that scope.
