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
- New table `excerpt_log`, written by `spr migrate`: one insert-only row per excerpt request, refused ones included.
  Run `spr migrate` before starting 0.2.0 of the API; the migration only adds.
- The 401, 404, 429 and 503 responses of `/ask` are now described in its OpenAPI document. Its behaviour and its
  response body are unchanged.
- Compose sets the rate limit to 60 requests a minute per person (the code's default stays 20) and adds `web/` to the
  API image's `.dockerignore`.
- CI gains jobs for the contract, the console's types, lint, tests, bundle budget, an image scan of both images, and
  browser journeys with Lighthouse against the compose stack.

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
