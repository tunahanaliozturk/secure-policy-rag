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

If you touch `web/`, run its gates too (Node 24):

```bash
cd web
npm ci
npm run type-check && npm run lint && npm run format:check
npm run test:unit                      # with coverage thresholds
npm run build && npm run size
npm run licences && npm audit --audit-level=high
npx playwright test                    # needs the compose stack up; see the README
npm run lighthouse                     # same
```

If you change a request or response model in `api.py` or `demo_login.py`, regenerate the contract and commit the
result. CI does the same and fails on any difference:

```bash
uv run spr openapi
cd web && npm run gen:api && npm run type-check
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
- **Every exit from `Assistant.ask` writes one audit record** before returning, and every excerpt request writes one
  `excerpt_log` row, found or not.
- **One way to read `chunks`.** Anything that reads a chunk for a caller goes through `store.reading_as`. A second
  query path is a second place for the access rule to be forgotten.
- **The API never issues a token.** Minting lives in `demo_login.py` and the `spr token` command; an import contract
  and a test on the API's routes hold the line.
- **The page computes no access and trusts no response.** A view shows what the server said to that person, and every
  response is parsed by a Zod schema tied to the generated type. No `as` at a network boundary, no `v-html`, no token
  in storage, no inline style (the content security policy would drop it).
- **Dependencies must be permissively licensed at every depth.** The licence audit fails the build otherwise. Add a
  dependency only when a few lines of code will not do.
- **Tests name the promise**, for example `a_revoked_token_is_refused`, not `test_token_3`. A test that cannot fail is
  not a test.
- **Docs: English, short sentences, no em dashes**, and every claim points at a test or a measurement. `test_docs.py`
  checks the configuration table and the dashes, in `web/` as well.

## Commits

Conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, `build:`, `ci:`), one logical change each.
