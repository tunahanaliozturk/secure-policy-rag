# Operations

## Configuration

Environment variables, read by `settings.py`; a `.env` file in the working directory is read too. The table is checked
against the code by `tests/unit/test_docs.py`, so a renamed setting fails the build until this page follows.

| Variable | Default | What raising or changing it costs |
|---|---|---|
| `SPR_DATABASE_URL` | `postgresql://spr_app@127.0.0.1:55440/policies` | Must connect as `spr_app`. Connecting as an owner or superuser silently switches row-level security off. |
| `SPR_ADMIN_DATABASE_URL` | unset | Only `spr migrate` and `spr ingest` use it. Never give it to the API. |
| `SPR_APP_DB_PASSWORD` | unset | Set on the `spr_app` role by `spr migrate`. Rotate by changing it and rerunning migrate, then restarting the API. |
| `SPR_TOKEN_SECRET` | unset | Required by `serve` and `token`; at least 32 bytes. The API refuses to start without it. |
| `SPR_TOKEN_SECRET_PREVIOUS` | unset | Still accepted for verification. Set it to the old secret during a rotation, remove it after the longest token lifetime. |
| `SPR_MODEL_PROVIDER` | `anthropic` | `scripted` answers offline with a stand-in; compose defaults to it. |
| `SPR_MODEL` | `claude-sonnet-5-5` | Changing the model is a model-risk decision (ADR 8). The audit log records the model that answered. |
| `SPR_EFFORT` | `medium` | Higher effort means more thinking tokens per answer: more latency and cost. |
| `SPR_EMBEDDER` | `fastembed` | `hashing` is for tests only. Ingest and serve must use the same embedder, or vector search returns noise. |
| `SPR_MODEL_CACHE_DIR` | unset (fastembed's default) | Where the embedding model lives. The image bakes it in at `/models`. |
| `SPR_RETRIEVERS` | `hybrid` | `vector` scored higher on the current evaluation set (ADR 7). Changing it needs a new `eval/baseline.json`. |
| `SPR_ALLOWED_LINK_HOSTS` | `intranet.bank.example` | Comma-separated. Every host added is a host a poisoned document can get shown to staff. |
| `SPR_TOP_K` | `5` | More excerpts per prompt: more context, more input tokens, more room for an injected document to be included. |
| `SPR_RATE_LIMIT_PER_MINUTE` | `20` | Per verified subject, per process. |
| `SPR_TRACE_EXPORTER` | `console` | `none` switches tracing off. Spans hold ids and counts, never text. |
| `SPR_LOG_LEVEL` | `INFO` | Logs hold ids, counts and outcomes, never question or answer text. |
| `ANTHROPIC_API_KEY` | unset | Read by the Anthropic SDK when `SPR_MODEL_PROVIDER=anthropic`. |

## What to watch

The audit log is the main signal. Useful queries, run as the administrator:

```sql
-- Outcomes over the last day. A rise in "blocked" means the model is citing or linking badly; read the violations.
select outcome, count(*) from audit_log where at > now() - interval '1 day' group by outcome;

-- Which guard fired, and how often.
select unnest(violations) as violation, count(*) from audit_log
where at > now() - interval '7 days' group by 1 order by 2 desc;

-- Personal data people type into questions, by kind.
select key, sum(value::int) from audit_log, jsonb_each_text(redactions_in)
where at > now() - interval '7 days' group by key;
```

Suggested alerts, to be tuned on real traffic:

| Signal | Threshold | Why |
|---|---|---|
| Share of `blocked` answers | above 5 percent over an hour | Either the model changed behaviour or a document is poisoning answers. |
| `unretrieved_citation` violations | any | A model citing what it was not given is either hallucinating ids or following an injection. |
| `url_host_not_allowed` violations | any | A source contains a link to a foreign host and the model repeated it. Find the document. |
| `error` outcomes | above 1 percent over 15 minutes | Model API trouble, usually. |
| `model_refused` outcomes | any sustained rise | Questions are tripping safety classifiers; check whether a document is the cause. |

## Runbook

### Answers are being blocked, with `url_host_not_allowed` in the violations

Confirm: the query above shows `url_host_not_allowed:<host>`. Find the source:

```sql
select id, title from chunks where text like '%<host>%';   -- as the administrator
```

Act: if the document is poisoned, remove it from the corpus and rerun `spr ingest`. If the host is legitimate, add it
to `SPR_ALLOWED_LINK_HOSTS` and restart the API. Verify: new questions on that topic come back `answered`.

Do not add a host just to make the alert stop. The allow-list is the only thing between a poisoned page and a
phishing link shown to staff.

### A user reports that someone saw a document they should not have

Confirm with the audit log, which lists every chunk retrieved for every question:

```sql
select at, subject, departments, clearance, retrieved_chunk_ids from audit_log
where '<chunk id>' = any(retrieved_chunk_ids) order by at desc;
```

If the subject's clearance and departments allow that chunk under the rule in ADR 2, the system worked and the
question is about the document's classification, which is set upstream. If they do not, treat it as a security
incident: stop the API, preserve the database, and check whether the API connected as a role other than `spr_app`
(the most likely cause, since that silently disables row-level security).

Do not change the policy in `schema.sql` during the incident. It is the evidence.

### The API will not start: "SPR_TOKEN_SECRET is not set" or "at least 32 bytes"

Set a secret of at least 32 bytes, for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`. If you
rotated, keep the old one in `SPR_TOKEN_SECRET_PREVIOUS` for an hour so signed-in users are not cut off.

### Retrieval returns irrelevant chunks after a deploy

Confirm: `spr eval-retrieval` scores far below `eval/baseline.json`. The usual cause is an embedder mismatch: chunks
ingested with one model, questions embedded with another. Act: rerun `spr ingest` with the same `SPR_EMBEDDER` the API
uses. Verify: the evaluation is back at baseline.

### Questions get slow, tens of milliseconds before the model is even called

Check that the embedder thread cap in `embedding.FastEmbedder` is still in place. With onnxruntime's default thread
pool, retrieval after an embedding went from 5.5 ms to 84 ms on a 16-thread laptop
(docs/benchmark-results/2026-10-06-laptop.md).

## Known limitations

- Rate limits live in process memory: each replica has its own, and they reset on restart.
- Ingestion replaces the whole corpus in one transaction. Fine at 149 chunks, slow at hundreds of thousands.
- Exact vector search scans every visible chunk. Past roughly a hundred thousand chunks, add an HNSW index and test
  that row-level filtering does not starve it (pgvector's iterative scan).
- Tokens cannot be revoked before they expire (ADR 5).
- Names, addresses and dates of birth are not redacted (ADR 3).
- Only English policies: the full-text configuration is `english`.
- The audit log grows forever. A bank would set a retention period for it in the retention schedule, and partition it
  by month.
