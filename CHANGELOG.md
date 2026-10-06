# Changelog

## Unreleased

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
