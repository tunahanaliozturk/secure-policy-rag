# Contributing

Thanks for looking. This is a portfolio project, so the bar for a change is that it keeps every guarantee in the README
true and provable.

## Before you open a pull request

Run the same gates CI runs:

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests benchmarks
uv run lint-imports
uv run pytest tests/unit
uv run pytest tests/integration        # needs Docker
uv run python tools/license_audit.py
```

If you touch retrieval, chunking or the corpus, also run the retrieval evaluation against the compose database
(`uv run spr eval-retrieval`) and say in the pull request how the numbers moved. Only regenerate
`eval/baseline.json` when a change is meant to move them, and explain why in the same commit.

## Rules that are easy to break by accident

- **Access decisions belong in `schema.sql`.** Do not add filtering by clearance or department in Python; the point is
  that Python cannot get it wrong. A new table that holds document text needs row-level security, forced, and a test
  in `test_access_control.py`.
- **No text in logs or spans.** Log ids, counts and outcomes. The sentinel test in `test_audit.py` will catch most
  slips; please do not weaken it.
- **Every exit from `Assistant.ask` writes one audit record** before returning.
- **Dependencies must be permissively licensed at every depth.** The licence audit fails the build otherwise. Add a
  dependency only when a few lines of code will not do.
- **Tests name the promise**, for example `a_revoked_token_is_refused`, not `test_token_3`. A test that cannot fail is
  not a test.
- **Docs: English, short sentences, no em dashes**, and every claim points at a test or a measurement. `test_docs.py`
  checks the configuration table and the dashes.

## Commits

Conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, `build:`, `ci:`), one logical change each.
