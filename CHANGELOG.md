# Changelog

## 0.2.0 (2026-10-13)

A browser console, and the two server additions it needs.

- **Console at `http://127.0.0.1:8440`** (`web/`, served by a new `web` service in compose). Sign in as one of the six
  demo people, ask a question, open a cited source, and ask one question as all six at once to see who cites what and
  who may open which source.
- **`GET /excerpts/{chunk_id}`** returns the text, title, section, classification and department of one chunk, read as
  the caller under the same row-level security as retrieval and redacted like an answer. A chunk the caller may not
  read is the same 404 as a chunk that does not exist. Excerpt requests count against the caller's rate limit.
- **`spr demo-login`**, a separate process (compose service `login`, port 8441): `POST /token` gives a ten-minute token
  to one of the six demo identities and to nobody else, and `GET /identities` lists them. The API still issues no
  tokens.
- **`spr openapi`** writes the OpenAPI documents of both servers; the console's TypeScript types are generated from
  them, and CI fails when the committed files differ from what the code serves.
- New table `excerpt_log`, written by `spr migrate`: one insert-only row for every excerpt request that reaches the
  database, with its outcome: `found`, `not_found` (hidden or absent, the database does not say which) or `error`
  (the read failed). A request refused before that writes no row: 401 for no valid token, 422 for an id that is not
  shaped like one, 429 for the rate limit. Run `spr migrate` before starting 0.2.0 of the API; the migration only
  adds.
- The 401, 429 and 503 responses of `/ask` are now described in its OpenAPI document, next to the 422 that was
  already there. Its behaviour and its response body are unchanged.
- Neither server serves `/docs`, `/redoc` or `/openapi.json` any more, and neither redirects a trailing slash.
  `spr openapi` writes the documents from the code.
- The API and the demo login no longer write an access log or the web framework's own request spans. Both recorded
  the path and query string of every request as the caller typed them; the spans opened by the pipeline are unchanged.
- Compose sets the rate limit to 60 requests a minute per person (the code's default stays 20) and adds `web/` to the
  API image's `.dockerignore`.
- CI gains jobs for the contract, the console's types, lint, tests, bundle budget, an image scan of both images, and
  browser journeys with Lighthouse against the compose stack.
- Fixed before release, from review, each with a test: the question someone asked is in the console's address, and
  nginx wrote that address and its Referer to the web log (the log now holds the path only, and
  `tools/smoke.py` fails if a marked question reaches any log); the same check found the API printing the query
  string of every request in a span and an access log, both now off; the `api` service was given the
  administrator's database address and the application role's password (only `setup` gets them now); an excerpt
  showed a poisoned source's link to a host off the allow-list, which an answer would be blocked for; a comparison
  address opened from a link asked as all six people without a click; the demo login and nginx answered to any host
  name, the precondition for DNS rebinding; signing out did not stop a token already on its way from being kept
  and used; a chunk id written in another script's digits reached the database and the record instead of a 422; a
  trailing slash was redirected, before authentication, to an address without the proxy's port and prefix; a missing
  asset was cached for a year, and a view whose script failed to load was a click that did nothing; answers of the
  API and the login could be written to the browser's cache, which sign-out does not clear; a read that failed in
  the database left no record; an unknown reader in a comparison address was reported as a source that person
  cannot open; a refusal's body was never read, which left the request open in the browser; and every Lighthouse
  limit was judged on the best of three runs (now the median).

## 0.1.0 (2026-10-06)

First version.

- Ask questions about 35 synthetic bank policies through `POST /ask` with a signed bearer token.
- Access control by Postgres row-level security on department and clearance; the application role owns nothing and
  cannot bypass it.
- Hybrid retrieval (Postgres full text and pgvector, fused by reciprocal rank fusion) with a local embedding model
  that works offline after one download.
- Personal data redacted from questions and answers: IBAN, card numbers, Turkish and Dutch national ids (all with
  check digits), email addresses and phone numbers.
- Answers must cite retrieved chunks and may only link to allowed hosts that appear in a source; otherwise they are
  blocked.
- Append-only audit log with redacted text, retrieved and cited chunk ids, redaction counts, model, latency and tokens.
- Retrieval evaluation with a CI gate, and whole-pipeline evaluation with scripted models.
