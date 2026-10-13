# Threat model

## On a napkin

**Who is the attacker?** Mostly an insider: an employee, contractor or compromised staff account that is allowed to
use the assistant. Second, anyone who can edit a policy document that gets ingested. Third, the model itself, which is
not an attacker but can be steered by one and is not trusted to follow its rules.

**What do they want?** Text they are not cleared for: the restricted AML investigations, the salary bands, the
incident runbook. Or personal data of customers. Or to use the assistant to phish colleagues ("sign in here").

**What do they already have?** A valid token, real questions, unlimited patience to rephrase, and in the second case
write access to a document the assistant will read. They do not have database credentials or the token secret.

**What does a win look like?** One restricted sentence in an answer, a control code from a document they cannot see,
a customer's IBAN in a log, or a link to their own site shown to a colleague as if the bank had said it.

So the design spends its effort on authorisation at the data layer, on not trusting the model's output, and on keeping
personal data out of everything that is stored. TLS, password policy and network controls matter, but they are the
platform's job and are out of scope here.

## What enforces what

| Threat | Control | Where it lives | Evidence |
|---|---|---|---|
| Reader sees a chunk above their clearance or outside their department | Row-level security policy, forced, on a non-owner role without `BYPASSRLS` | `schema.sql` | `test_access_control.py`: every demo user sees exactly the chunks the rule allows; an unfiltered query returns no restricted row; the app role cannot disable or drop the policy |
| A bug in retrieval code drops the filter | Same: the filter is not in the code | `schema.sql` | `test_an_unfiltered_query_from_buggy_app_code_still_returns_no_restricted_rows` |
| Request runs without saying who asks | Unset settings mean clearance -1 and no departments | `schema.sql` | `test_a_query_with_no_reader_set_sees_nothing` |
| Identity leaks between pooled requests | Settings are transaction-local | `store.set_reader` | `test_reader_settings_end_with_the_transaction...` |
| Caller raises their own clearance | Signed claims, constant-time compare, fixed claim values, expiry | `identity.py` | `test_identity.py` |
| Personal data reaches the model, logs, spans or audit | Redaction before retrieval and before the model; logs and spans carry counts only | `pii.py`, `pipeline.py` | `test_personal_data_in_a_question_reaches_no_log_span_audit_record_or_answer` (sentinel values) |
| Model repeats personal data found in a source | Answer redacted before return | `pipeline._finish` | `test_personal_data_the_model_copies_from_a_source_is_redacted...`, answer cases a10, a11 |
| Poisoned document instructs the model | Fenced and escaped excerpts, instruction in the system prompt, no tools | `prompt.py`, `model.py` | `test_guards.py`, answer cases a12, a15 |
| Model cites something it was not given | Every citation must be retrieved for this reader | `verify.py` | answer case a07, `test_guards.py` |
| Model shows a phishing link or leaks data in a URL | Links must appear verbatim in a source and use an allowed host | `verify.py` | answer cases a08, a14, `test_guards.py` |
| Audit record altered or backdated | Insert-only grant on listed columns; database stamps id and time | `schema.sql` | `test_the_application_cannot_read_change_delete_or_backdate_audit_records` |
| A refusal reveals that a restricted document exists | One refusal text for every reason | `pipeline.REFUSAL` | answer cases a04, a05 |
| One user floods the model | Token bucket per verified subject | `api.RateLimiter` | `test_the_rate_limit_applies_per_verified_subject` |
| Reader opens a cited chunk by id that they may not read, or probes ids to learn what exists | The excerpt endpoint reads through the same row-level security; one 404 for hidden and absent | `store.reading_as`, `api.py` | `test_a_restricted_chunk_the_caller_may_not_read_is_the_same_404_as_a_chunk_that_does_not_exist`, `test_every_reader_can_open_exactly_the_chunks_the_access_rule_allows` |
| Opening a source shows personal data an answer would have hidden | Excerpt text redacted like an answer | `pipeline.Assistant.excerpt` | `test_personal_data_in_a_source_is_redacted_in_the_excerpt_as_it_is_in_an_answer` |
| Opening a poisoned source shows the phishing link an answer would have been blocked for | Links to hosts off the allow-list replaced with a marker, by the pattern and allow-list the answer check uses | `verify.withhold_links` | `test_a_link_a_poisoned_source_plants_is_withheld_from_the_excerpt_as_it_is_from_an_answer`; `tools/smoke.py` against the stack |
| A question with personal data in it reaches a log through the address it sits in (`/ask?q=`), or through a Referer | nginx logs the path cut at the question mark and no Referer, and no error-level lines; the API and the login write no access log and none of the web framework's request spans | `web/nginx.conf`, `cli.py`, `telemetry.FRAMEWORK_TELEMETRY` | `tools/smoke.py` (a marked question must be in no log of web, api or login); `test_text_a_caller_puts_in_an_address_reaches_no_span_or_log_line` |
| Caller-chosen text in the excerpt path reaches the log or the read record | Path validated against the shape of a chunk id first | `api.CHUNK_ID` | `test_an_id_that_is_not_shaped_like_a_chunk_id_is_rejected_and_reaches_no_log_or_record` |
| Excerpt reads leave no trace, or the trace is altered | Insert-only `excerpt_log` with an outcome for every request that reaches the database (found, not found, failed), database-stamped time. Requests refused with 401, 422 or 429 write no row | `schema.sql` | `test_every_excerpt_request_is_recorded...`, `test_a_read_that_fails_in_the_database_is_recorded_as_an_error_and_answered_503`, `test_the_application_cannot_read_change_delete_or_backdate_excerpt_records` |
| The API is talked into minting a token | It has no route that issues one; the demo login is another process | `demo_login.py`, import contract | `test_the_api_process_has_no_route_that_could_mint_a_token`, `lint-imports` |
| Someone gets a demo token with a clearance of their choosing | Six fixed identities; any other name is a 404, any extra field a 422 | `demo_login.py` | `test_demo_login.py` |
| A page on another site reaches the login on 127.0.0.1 through the visitor's browser (DNS rebinding) and takes a token | The login (port 8441) refuses any host name it was not started for; nginx (port 8440) drops a request addressed to any name but 127.0.0.1 and localhost | `demo_login.py`, `web/nginx.conf` | `test_a_request_addressed_to_another_host_name_gets_no_token`; `tools/smoke.py` |
| The API process holds credentials that get around row-level security | Only the one-shot `setup` service is given the administrator's address and the application role's password | `compose.yaml` | `tools/smoke.py` reads the resolved compose file |
| A link makes someone's browser spend model calls | A question that arrives with the address is shown and not sent until a button is pressed | `web/src/features/compare/CompareView.vue`, `web/src/router.ts` | `CompareView.test.ts`; journey "the same question as six people" (no request before the press) |
| Restricted text or a token stays in the browser's HTTP cache after sign-out | `Cache-Control: no-store` on everything under `/api/` and `/login/` | `web/nginx.conf` | journey "every location on the one origin"; `tools/smoke.py` |
| A token asked for before sign-out is kept and used after it | Tokens are tied to a count of sign-outs and dropped when they land late; queries in flight are cancelled | `web/src/shared/api/tokens.ts`, `login.ts` | `api.test.ts`, `CompareView.test.ts` ("stops when the person signs out") |
| A script on the page reads the bearer token | Token in module memory only; no inline script or style, no other origin | `web/src/shared/api/tokens.ts`, `web/spr-headers.conf` | journey "a person signs in, asks" (storage and cookies empty); journey "every response on the one origin carries the security headers"; every journey fails on a reported CSP violation |
| The page shows text the server did not return to this reader | The page computes no access; every cell is a request made as that person | `web/src/features/compare/AccessCell.vue` | `CompareView.test.ts`; journeys "the same question as six people" and "a source the person may not read cannot be opened by editing the address" |
| A model answer carries markup or a link that the page renders | Answers rendered as text only; `v-html` is a lint error | `web/src/features/ask/AnswerPanel.vue` | `web/eslint.config.ts` (`vue/no-v-html`) |

## OWASP Top 10 for LLM Applications (2025)

| Risk | Covered here | Not covered |
|---|---|---|
| LLM01 Prompt injection | Layers in ADR 4: nothing above the reader's clearance in the prompt, fenced data, no tools, output verification. Four poisoned documents in the corpus and answer cases that simulate a model following them. | A persuasive injection that makes the model state something false, with a valid citation and no link, passes every check. No real-model run exists to say how often that happens. |
| LLM02 Sensitive information disclosure | Row-level security, PII redaction both ways, audit with redacted text only, a refusal that does not reveal what exists. | Names, addresses and dates of birth are not detected (ADR 3). Text within the reader's own clearance is shown as written, by design. |
| LLM03 Supply chain | Locked dependencies for Python and npm, a licence audit for each, pip-audit and `npm audit` in CI, Trivy on both images failing on fixable HIGH findings, embedding model baked into the image so nothing downloads at run time, onnxruntime telemetry switched off. | Actions are pinned to tags, not commit hashes. No signature check on the downloaded embedding model beyond the hub's own. Lighthouse runs from npm at a pinned version, outside the lockfile. |
| LLM04 Data and model poisoning | Poisoned documents are contained by the same layers as LLM01. Ingestion runs as an administrator role the app does not hold. | No review or signing of documents before ingestion, and no scan that flags instruction-like text in new documents. |
| LLM05 Improper output handling | Answers are checked for citations and links, then redacted, and returned as JSON data. The browser console renders them as text: no HTML, no auto-linking, and a content security policy that allows no inline script. | Another client must still escape the answer. Markdown in answers is not stripped, so the console shows it as typed. A bare domain with no scheme, `//` or `www.` (`portal.example.net/login`) is not recognised as a link, so a client must not auto-link one. |
| LLM06 Excessive agency | The model has no tools and makes one call per question. | Nothing further to cover today; adding tools would reopen this. |
| LLM07 System prompt leakage | The system prompt holds no secrets, so leaking it costs nothing. | Not tested; there is nothing to protect in it. |
| LLM08 Vector and embedding weaknesses | Access control applies to the vector search itself, not after it. Exact search, so no approximate index can drop rows under the filter. | Embeddings are stored in the clear; anyone with database access can attempt inversion. That is the same people who can read the text. |
| LLM09 Misinformation | Every answer must cite retrieved sources; the model is told to refuse when the sources do not cover the question. | Whether the cited source actually supports the sentence is only checked by the optional faithfulness judge, which has not been run. |
| LLM10 Unbounded consumption | Rate limit per subject, question length capped at 2,000 characters, five excerpts per prompt, `max_tokens` capped. The console sends nothing for a question that arrived with a link until a button is pressed. | Rate limits are per process; no cost budget per user or per day. One press of "Ask as all six" is six model calls. |

## Known gaps, stated once

- **Trusted settings.** The database trusts the clearance the application sets. SQL injection into the application's
  own connection could raise it. Parameterised SQL is the defence; a `SECURITY DEFINER` function verifying a signed
  token inside Postgres would close it (ADR 2). A test shows the gap exists.
- **Names are not personal data to this code.** See ADR 3.
- **No real-model numbers.** There is no API key on the machine this was built on. Every answer-quality claim in this
  repository is about the guards, measured with scripted models, not about Claude.
- **Demo identity.** HMAC tokens without revocation stand in for the bank's identity provider (ADR 5).
- **The demo login has no passwords.** Anyone who can reach it can be any of the six people, restricted clearance
  included (ADR 10). Compose binds it to 127.0.0.1, on port 8441 directly and on port 8440 behind the console's
  nginx, and both refuse a request addressed to another host name. Exposing either port is exposing every document
  in the corpus.
- **The web log holds paths.** nginx records the path of every request as it was typed, without the query string. A
  question is never in a path, but anything else a caller types into one is logged.
- **A token in the browser is a token an injected script could use.** It is kept out of storage, and the content
  security policy allows no script but the page's own, but script that did run on the page could call the API as the
  signed-in person for as long as the page is open. An `HttpOnly` cookie set by the identity provider would close
  that; this demo has no such provider (ADR 11).
- **The comparison view is a demo-only convenience.** It signs in as all six people at once, which no real user can
  do, and its probes fill `excerpt_log` with refused reads that would look like an attack anywhere else.
- **Documents are trusted to be classified correctly.** A restricted text filed as internal is shown to everyone
  internal. Classification is an upstream process this system cannot check.
