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

## OWASP Top 10 for LLM Applications (2025)

| Risk | Covered here | Not covered |
|---|---|---|
| LLM01 Prompt injection | Layers in ADR 4: nothing above the reader's clearance in the prompt, fenced data, no tools, output verification. Four poisoned documents in the corpus and answer cases that simulate a model following them. | A persuasive injection that makes the model state something false, with a valid citation and no link, passes every check. No real-model run exists to say how often that happens. |
| LLM02 Sensitive information disclosure | Row-level security, PII redaction both ways, audit with redacted text only, a refusal that does not reveal what exists. | Names, addresses and dates of birth are not detected (ADR 3). Text within the reader's own clearance is shown as written, by design. |
| LLM03 Supply chain | Locked dependencies, licence audit, pip-audit in CI, embedding model baked into the image so nothing downloads at run time, onnxruntime telemetry switched off. | Actions are pinned to tags, not commit hashes. No signature check on the downloaded embedding model beyond the hub's own. No container image scan. |
| LLM04 Data and model poisoning | Poisoned documents are contained by the same layers as LLM01. Ingestion runs as an administrator role the app does not hold. | No review or signing of documents before ingestion, and no scan that flags instruction-like text in new documents. |
| LLM05 Improper output handling | Answers are checked for citations and links, then redacted, and returned as JSON data; nothing renders or executes them here. | The client that displays the answer must still escape it. Markdown in answers is not stripped. |
| LLM06 Excessive agency | The model has no tools and makes one call per question. | Nothing further to cover today; adding tools would reopen this. |
| LLM07 System prompt leakage | The system prompt holds no secrets, so leaking it costs nothing. | Not tested; there is nothing to protect in it. |
| LLM08 Vector and embedding weaknesses | Access control applies to the vector search itself, not after it. Exact search, so no approximate index can drop rows under the filter. | Embeddings are stored in the clear; anyone with database access can attempt inversion. That is the same people who can read the text. |
| LLM09 Misinformation | Every answer must cite retrieved sources; the model is told to refuse when the sources do not cover the question. | Whether the cited source actually supports the sentence is only checked by the optional faithfulness judge, which has not been run. |
| LLM10 Unbounded consumption | Rate limit per subject, question length capped at 2,000 characters, five excerpts per prompt, `max_tokens` capped. | Rate limits are per process; no cost budget per user or per day. |

## Known gaps, stated once

- **Trusted settings.** The database trusts the clearance the application sets. SQL injection into the application's
  own connection could raise it. Parameterised SQL is the defence; a `SECURITY DEFINER` function verifying a signed
  token inside Postgres would close it (ADR 2). A test shows the gap exists.
- **Names are not personal data to this code.** See ADR 3.
- **No real-model numbers.** There is no API key on the machine this was built on. Every answer-quality claim in this
  repository is about the guards, measured with scripted models, not about Claude.
- **Demo identity.** HMAC tokens without revocation stand in for the bank's identity provider (ADR 5).
- **Documents are trusted to be classified correctly.** A restricted text filed as internal is shown to everyone
  internal. Classification is an upstream process this system cannot check.
