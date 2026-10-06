# secure-policy-rag

[![ci](https://github.com/tunahanaliozturk/secure-policy-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/tunahanaliozturk/secure-policy-rag/actions/workflows/ci.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

A policy assistant for bank staff, built so that access control, personal-data redaction and citation checks hold even
when the model or the application code misbehaves.

- **Access control lives in Postgres, not Python.** Over 69 evaluation questions asked by six users with different
  clearances, 0 chunks came back that the user was not allowed to read, and a retrieval query with its filter deleted
  still returns none (`tests/integration/test_access_control.py`).
- **The guards hold against a model that misbehaves on purpose.** All 16 whole-pipeline cases pass, including stand-in
  models that cite what they were not given, invent or repeat links, skip citations, or copy customer data from a
  source. No personal data and no foreign link reaches the user (`eval/answers.jsonl`).
- **The guards are cheap.** Redaction, embedding, retrieval under row-level security, verification and the audit
  insert take 17.3 ms at the median and 21.0 ms at p95, on an Intel Core Ultra 7 255H laptop
  (`docs/benchmark-results/2026-10-06-laptop.md`).

There is no API key on the machine this was built on, so **nothing here measures Claude's answers**. Every number is
about retrieval and the guards around the model. [docs/evaluation.md](docs/evaluation.md) says exactly what was and was
not run.

## Quick start

Needs Docker. Answers come from a deterministic stand-in model unless you set `SPR_MODEL_PROVIDER=anthropic` and
`ANTHROPIC_API_KEY`.

```bash
export SPR_TOKEN_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
docker compose up --build --detach --wait
TOKEN=$(docker compose exec -T api spr token dave)
curl -s 127.0.0.1:8400/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question": "How long must my password be?"}'
```

```json
{"outcome":"answered","answer":"Passwords for personal accounts must be at least 14 characters long. [SEC-002#1]",
 "citations":[{"chunk_id":"SEC-002#1","title":"Password and Multi-Factor Authentication Standard","section":"1. Password length"}],
 "question_redactions":{}}
```

Now ask as `erin` (security, restricted clearance) and as `dave` (markets, internal) which systems are the crown jewel
systems. Erin's answer cites the restricted incident runbook. Dave's never does, because the database does not return
that chunk to him. `requests.http` walks through more, and CI runs these commands on every push (`tools/smoke.py`).

| Demo user | Departments | Clearance |
|---|---|---|
| alice | credit | confidential |
| bob | compliance | restricted |
| carol | hr | confidential |
| dave | markets | internal |
| erin | security, data | restricted |
| frank | none (contractor) | public |

## How a question is answered

```
POST /ask  (signed bearer token: subject, departments, clearance, expiry)
  │
  ├─ redact      IBAN, card, TCKN, BSN, email, phone  → [IBAN_1] ...   (pii.py)
  ├─ retrieve    as this reader: set_config(clearance, departments), then
  │              full text + vector in one transaction, fused by RRF   (store.py, schema.sql)
  │              row-level security decides what exists for this reader
  ├─ generate    Claude, one call, no tools, JSON schema output;
  │              excerpts fenced and escaped as untrusted data          (prompt.py, model.py)
  ├─ verify      every citation retrieved for this reader, at least one;
  │              links only if verbatim in a source and on an allowed host (verify.py)
  ├─ redact      the answer, in case the model copied personal data from a source
  └─ audit       append-only row: who, what was retrieved and cited, redaction counts,
                 model, latency, tokens. Written before the answer is returned. (pipeline.py)
```

Each step is an OpenTelemetry span; spans and logs carry ids and counts, never text.

## The decision that matters most

The obvious place to enforce "Dave may not read restricted HR documents" is a `WHERE` clause in the retrieval query.
It works until someone writes a second query, or refactors the first, and in a RAG system the failure is silent: the
model just has more to quote. Here the rule is a row-level security policy on the `chunks` table, forced, for a role
that owns nothing and cannot bypass it. The application only says who is asking, through two transaction-local
settings taken from a verified token. If it forgets to say, the reader is nobody and sees nothing. The integration
tests check every demo user against an independent Python statement of the rule, run an unfiltered query to show it
still returns nothing restricted, and show the app role cannot disable, drop or rewrite the policy. The honest limit:
the database trusts the settings, so SQL injection into the application's own connection could raise them. That is
written down in [ADR 2](docs/adr/0002-access-control-in-postgres-row-level-security.md) and pinned by a test.

## Threat model in brief

The attacker is mostly an insider with a valid login who wants text above their clearance, plus anyone who can edit a
policy document the assistant reads. [docs/threat-model.md](docs/threat-model.md) has the full table and an OWASP Top
10 for LLM Applications (2025) mapping, including what is not covered.

| Risk | Defence | Proven by |
|---|---|---|
| Reading above your clearance | Postgres row-level security | `test_access_control.py`, 0 leaks in the retrieval evaluation |
| Personal data in prompts, logs, audit | Checksum-validated redaction both ways | sentinel test across answer, logs, spans and audit row |
| Poisoned document gives orders | No tools, fenced excerpts, answer verification | four poisoned documents, answer cases a07, a08, a12, a14, a15 |
| Phishing link in an answer | Link must be in a source and on an allowed host | `test_guards.py`, case a14 |
| Tampered audit trail | Insert-only column grant, database-stamped time | `test_audit.py` |

## Measured results

Retrieval, 56 answerable questions plus 13 that the asker must not be able to answer, top 5, bge-small-en-v1.5,
Postgres 18 with pgvector 0.8.7, on 2026-10-06 ([docs/evaluation.md](docs/evaluation.md)):

| Retrieval | recall@5 | nDCG@5 | Leaks |
|---|---|---|---|
| Hybrid, RRF k = 60 (default) | 0.982 | 0.937 | 0 |
| Full text only | 0.929 | 0.881 | 0 |
| Vector only | 1.000 | 1.000 | 0 |

Vector search alone beat hybrid on this set, which is not what we expected. Hybrid stays the default for reasons
[ADR 7](docs/adr/0007-hybrid-retrieval-kept-despite-vector-scoring-higher.md) gives, and `SPR_RETRIEVERS=vector` is one
setting away. CI fails if hybrid drops more than 0.02 below `eval/baseline.json`, or on any leak.

Latency of everything except the model call: 17.3 ms p50, 21.0 ms p95, 36.1 ms p99 over 345 sequential requests. The
first measurement was 89.7 ms p50: onnxruntime's default thread pool kept spinning after each embedding and starved the
event loop. Capping it at two threads fixed it; the story is in the benchmark file.

Tests: 86 unit tests (offline), 48 integration tests (real Postgres in Docker).

## Limitations

- No real-model evaluation. The faithfulness judge (`spr eval-answers --model anthropic --judge`) exists and has never
  run.
- Names, addresses and dates of birth are not detected as personal data ([ADR 3](docs/adr/0003-pii-recognisers-with-check-digits.md)).
- A persuasive injection that makes the model state something false, with a valid citation and no link, passes every
  check ([ADR 4](docs/adr/0004-layered-prompt-injection-defence.md)).
- Demo tokens have no revocation; a bank would use its identity provider ([ADR 5](docs/adr/0005-signed-demo-tokens.md)).
- Rate limits are per process. The corpus is 35 synthetic documents, 149 chunks; the evaluation sets were written by
  the same person, which flatters every retriever.

## Documentation

- [docs/threat-model.md](docs/threat-model.md): attacker, controls, OWASP LLM mapping, gaps
- [docs/evaluation.md](docs/evaluation.md): both evaluations, results, what they do not show
- [docs/operations.md](docs/operations.md): configuration, what to watch, runbook, known limitations
- [docs/benchmark-results/2026-10-06-laptop.md](docs/benchmark-results/2026-10-06-laptop.md): latency and the thread-pool finding
- Decisions: [1 Python 3.14 and licences](docs/adr/0001-python-3.14-uv-and-permissive-dependencies.md),
  [2 row-level security](docs/adr/0002-access-control-in-postgres-row-level-security.md),
  [3 PII recognisers](docs/adr/0003-pii-recognisers-with-check-digits.md),
  [4 injection layers](docs/adr/0004-layered-prompt-injection-defence.md),
  [5 demo tokens](docs/adr/0005-signed-demo-tokens.md),
  [6 no LangGraph](docs/adr/0006-plain-pipeline-not-langgraph.md),
  [7 hybrid retrieval](docs/adr/0007-hybrid-retrieval-kept-despite-vector-scoring-higher.md),
  [8 no model fallback](docs/adr/0008-no-automatic-model-fallback.md)

## Development

Python 3.14 and [uv](https://docs.astral.sh/uv/). Docker for the integration tests, which start Postgres with
testcontainers unless `SPR_TEST_ADMIN_DSN` points at one.

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests benchmarks && uv run lint-imports
uv run pytest tests/unit
uv run pytest tests/integration
uv run python tools/license_audit.py
```

The evaluations need the compose database with the corpus loaded by the real embedder; `.env.example` has the
variables:

```bash
uv run spr eval-retrieval
uv run spr eval-answers
```

Stack: FastAPI, asyncpg, Postgres 18 with pgvector, fastembed with onnxruntime, the Anthropic Python SDK, Pydantic,
OpenTelemetry, structlog. Every dependency, at every depth, is under a permissive licence (`tools/license_audit.py`).

## Licence

MIT. The policy documents in `corpus/` are fictional; the people, accounts and identifiers in them are invented, and
the identifiers are published test values chosen because their check digits are valid.
