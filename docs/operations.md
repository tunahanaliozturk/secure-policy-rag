# Operations

## Configuration

Environment variables, read by `settings.py`; a `.env` file in the working directory is read too. The table is checked
against the code by `tests/unit/test_docs.py`, so a renamed setting fails the build until this page follows.

| Variable | Default | What raising or changing it costs |
|---|---|---|
| `SPR_DATABASE_URL` | `postgresql://spr_app@127.0.0.1:55440/policies` | Must connect as `spr_app`. Connecting as an owner or superuser silently switches row-level security off. |
| `SPR_ADMIN_DATABASE_URL` | unset | Only `spr migrate` and `spr ingest` use it. Never give it to the API. |
| `SPR_APP_DB_PASSWORD` | unset | Set on the `spr_app` role by `spr migrate`. Rotate by changing it and rerunning migrate, then restarting the API. |
| `SPR_TOKEN_SECRET` | unset | Required by `serve`, `token` and `demo-login`; at least 32 bytes. The API refuses to start without it. The demo login signs with it, so the two must hold the same value. |
| `SPR_TOKEN_SECRET_PREVIOUS` | unset | Still accepted for verification. Set it to the old secret during a rotation, remove it after the longest token lifetime. |
| `SPR_MODEL_PROVIDER` | `anthropic` | `scripted` answers offline with a stand-in; compose defaults to it. |
| `SPR_MODEL` | `claude-sonnet-5-5` | Changing the model is a model-risk decision (ADR 8). The audit log records the model that answered. |
| `SPR_EFFORT` | `medium` | Higher effort means more thinking tokens per answer: more latency and cost. |
| `SPR_EMBEDDER` | `fastembed` | `hashing` is for tests only. Ingest and serve must use the same embedder, or vector search returns noise. |
| `SPR_MODEL_CACHE_DIR` | unset (fastembed's default) | Where the embedding model lives. The image bakes it in at `/models`. |
| `SPR_RETRIEVERS` | `hybrid` | `vector` scored higher on the current evaluation set (ADR 7). Changing it needs a new `eval/baseline.json`. |
| `SPR_ALLOWED_LINK_HOSTS` | `intranet.bank.example` | Comma-separated. Every host added is a host a poisoned document can get shown to staff. |
| `SPR_TOP_K` | `5` | More excerpts per prompt: more context, more input tokens, more room for an injected document to be included. |
| `SPR_RATE_LIMIT_PER_MINUTE` | `20` | Per verified subject, per process. Questions and excerpt requests draw on the same allowance. Compose sets 60, because one comparison in the console sends a question and up to six excerpt requests as each person. |
| `SPR_TRACE_EXPORTER` | `console` | `none` switches tracing off. Spans hold ids and counts, never text. |
| `SPR_LOG_LEVEL` | `INFO` | Logs hold ids, counts and outcomes, never question or answer text. |
| `ANTHROPIC_API_KEY` | unset | Read by the Anthropic SDK when `SPR_MODEL_PROVIDER=anthropic`. |

## What runs in the compose stack

| Service | Address on the host | What it is |
|---|---|---|
| `postgres` | 127.0.0.1:55440 | Postgres 18 with pgvector. Holds the chunks, the audit log and the excerpt log. |
| `setup` | none | Runs `spr migrate` and `spr ingest` once, as the administrator, then exits. |
| `api` | 127.0.0.1:8400 | `POST /ask`, `GET /excerpts/{chunk_id}`, `GET /healthz`. Verifies tokens, never signs one. |
| `login` | 127.0.0.1:8441 | `spr demo-login`: `POST /token`, `GET /identities`. Ten-minute tokens for six demo people, no passwords (ADR 10). Gets the token secret and nothing else. |
| `web` | 127.0.0.1:8440 | nginx: the built console, `/api/` proxied to `api`, `/login/` proxied to `login`. One origin for the browser (ADR 11). |

Everything is bound to 127.0.0.1. The demo login must stay that way: whoever reaches it can be anyone.

The console as nginx serves it, measured on 2026-10-13 with Lighthouse 12.6.1 in Chrome 154 against the compose
stack on an Intel Core Ultra 7 255H laptop, phone emulation with Lighthouse's simulated throttling (150 ms round
trip, 1.6 Mbit/s, 4x CPU slowdown), two sessions of three runs each on the sign-in page:

| Measure | First session | Second session | Gate in `web/lighthouserc.json` |
|---|---|---|---|
| Performance score | 0.99, 0.99, 0.99 | 0.99, 0.95, 0.99 | at least 0.95 |
| Accessibility score | 1.0 | 1.0 | 1.0 |
| Largest contentful paint | 1,731, 1,720, 1,804 ms | 1,721, 2,004, 1,843 ms | under 2,500 ms |
| Cumulative layout shift | 0 | 0 | under 0.1 |
| Total blocking time | 12, 6, 21 ms | 7, 213, 40 ms | under 200 ms |
| Transfer for the first page, 10 requests | 85,300 bytes, of which 79,524 script | 85,300 bytes | none; `size-limit` bounds the build |

One run in six blocked for 213 ms, above the 200 ms limit, and the gate still passed. Lighthouse CI judges each limit
on the best of its three runs unless told otherwise, and `lighthouserc.json` does not tell it otherwise. So the gate
catches a page that is slow in every run, and lets through one that is slow in one run of three. The second session
ran straight after the browser journeys on the same laptop, which is the likeliest reason for that run; it was not
investigated further.

`size-limit` on the build: entry chunk 9.49 kB gzip against a 12 kB limit, and every script and style of all three
routes together 88.42 kB against 100 kB. nginx compresses at level 6; at its default, level 1, the largest script was
43,544 bytes on the wire instead of 37,980.

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

-- Who asked to open excerpts the database did not show them, and how often. One or two is a mistyped link.
-- A long run of different ids from one person is someone walking the id space.
select subject, count(*) as refused, count(distinct chunk_id) as different_ids from excerpt_log
where not found and at > now() - interval '1 day' group by subject order by refused desc;
```

The console's comparison view fills `excerpt_log` with refused reads by design: it asks for every cited source as
each of the six demo people. On a demo stack that is noise; the query above is for a deployment without that view.

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

Confirm with the two records. The audit log lists every chunk retrieved for every question, and the excerpt log
every chunk opened by id:

```sql
select at, subject, departments, clearance, retrieved_chunk_ids from audit_log
where '<chunk id>' = any(retrieved_chunk_ids) order by at desc;

select at, subject, departments, clearance from excerpt_log
where chunk_id = '<chunk id>' and found order by at desc;
```

If the subject's clearance and departments allow that chunk under the rule in ADR 2, the system worked and the
question is about the document's classification, which is set upstream. If they do not, treat it as a security
incident: stop the API, preserve the database, and check whether the API connected as a role other than `spr_app`
(the most likely cause, since that silently disables row-level security).

Do not change the policy in `schema.sql` during the incident. It is the evidence.

### The API will not start: "SPR_TOKEN_SECRET is not set" or "at least 32 bytes"

Set a secret of at least 32 bytes, for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`. If you
rotated, keep the old one in `SPR_TOKEN_SECRET_PREVIOUS` for an hour so signed-in users are not cut off.

### The console says "The assistant is unavailable" and gives no reference

A failure inside the API always comes with a reference, so no reference means nginx answered instead: it could not
reach the API. Confirm: `docker compose logs web` shows 502 or 504 for `/api/` requests, and `docker compose ps`
shows whether `api` is down, restarting or was recreated. Act: if `api` is down, start it; the console recovers on
its own once it is healthy (checked by stopping and starting the container). If `api` is healthy and the 502s go on,
nginx is still using the address the previous container had, because it resolves `api` and `login` when it starts:
`docker compose restart web`. Verify: `http://127.0.0.1:8440/api/healthz` returns `{"status":"ok"}`.

When there is a reference, search the API log for it: the line carries the error type and the path.

Do not point the browser at port 8400 to get around it. The console only works from its own origin; the content
security policy and the absence of CORS headers are deliberate.

### Every question in the console fails with "Sign-in expired"

The console renews a refused token once and gives up on the second refusal, so this means fresh tokens are being
refused. Confirm: `docker compose exec -T api spr token dave` gives a token that works with `curl` against port 8400
while the console's does not. The cause is two different values of `SPR_TOKEN_SECRET`: the login signs with one and
the API verifies with another, usually because one container was restarted after the variable changed. Act: restart
`api` and `login` with the same value. Verify: sign in again in the console and ask.

### The console says "Too many requests"

The message gives the wait the API asked for. It is the per-person rate limit, shared by questions and excerpt
requests; several comparisons in a row can reach it. Wait, or raise `SPR_RATE_LIMIT_PER_MINUTE` for the stack and
restart `api`. Do not raise it on anything that calls a paid model without also setting a budget.

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
- The audit log and the excerpt log grow forever. A bank would set a retention period for them in the retention
  schedule, and partition them by month.
- The demo login has no passwords and no rate limit of its own. It exists for the demo stack only (ADR 10).
- nginx in the `web` container resolves `api` and `login` once at start-up; recreate either and `web` needs a restart.
- The console is English only and has a light theme only.
- A reload of the console signs the person out: the token is kept in memory and nowhere else (ADR 11).
