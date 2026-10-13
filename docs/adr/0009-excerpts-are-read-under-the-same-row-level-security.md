# 9. A cited excerpt is read as the caller, under the same row-level security as retrieval

Status: Accepted, 2026-10-13

## Context

An answer cites chunks by id, and a reader wants to open one and read what was cited. Until now the API had one way
to reach `chunks`, retrieval, and one promise about it: the database decides what exists for the reader (ADR 2). A
second route to the same table is where that promise usually breaks, because it is written later, by hand, with its own
query and its own idea of who may see what. The id is also caller-chosen: anyone with a token can ask for `SEC-004#2`
whether or not an answer ever showed it to them.

## Decision

`GET /excerpts/{chunk_id}` reads one chunk through `store.reading_as`, the same read-only transaction with the same
`set_reader` call that retrieval now uses, and returns 404 with one fixed body whenever the query returns no row.

## Consequences

- The code cannot tell a chunk that is hidden from this reader from a chunk that does not exist, because the policy
  hands it the same empty result for both. So it cannot reveal which it was. For each of the six demo people,
  `test_a_restricted_chunk_the_caller_may_not_read_is_the_same_404_as_a_chunk_that_does_not_exist` compares status,
  body and headers of the two responses and requires them to be equal.
- The endpoint grants nothing retrieval did not. `test_every_reader_can_open_exactly_the_chunks_the_access_rule_allows`
  opens all 149 chunks as all six people and compares each result with the Python oracle `identity.can_read`.
- Excerpt text is held to the rules of an answer, so that opening a source shows no more than citing it did. A
  source can hold a worked example with a customer's IBAN; `/ask` removes it from answers, and it is removed here
  (`test_personal_data_in_a_source_is_redacted_in_the_excerpt_as_it_is_in_an_answer`). A poisoned source can hold
  a link to a foreign host; an answer repeating it is blocked, and here the link is replaced with a marker by the
  same pattern and the same allow-list (`verify.withhold_links`,
  `test_a_link_a_poisoned_source_plants_is_withheld_from_the_excerpt_as_it_is_from_an_answer`). The first version
  of this endpoint did the first and not the second; a review found the phishing link in an excerpt.
- Every request that reaches the database is written to a new insert-only table, `excerpt_log`, with who asked, for
  which id, and the outcome: `found`, `not_found` or `error`. A request for a chunk the reader may not open is
  recorded as `not_found`, so probing for ids shows up, and a read that fails is recorded as `error` before the 503
  goes out (`test_a_read_that_fails_in_the_database_is_recorded_as_an_error_and_answered_503`). A request refused
  before the database is reached writes no row: no valid token (401), an id that is not shaped like one (422), the
  rate limit (429). The application can insert and nothing else
  (`test_the_application_cannot_read_change_delete_or_backdate_excerpt_records`). This is a second audit table to
  keep and to query; the runbook entry for "someone saw a document they should not have" now needs both.
- The id in the path is validated against the shape of a chunk id before anything runs, with `[0-9]` and not `\d`,
  which also matches the digits of other scripts. Without that, a caller could put an IBAN in the path and have it
  written to the application's log line and the record
  (`test_an_id_that_is_not_shaped_like_a_chunk_id_is_rejected_and_reaches_no_log_or_record`). This covers what the
  application writes. A proxy in front of it still logs the path of every request as it was typed; the console's
  nginx logs the path and nothing after the question mark.
- Excerpt requests count against the same per-person rate limit as questions
  (`test_excerpt_requests_and_questions_share_one_rate_limit_per_subject`). Someone reading many sources can therefore
  use up their questions for that minute.
- A 404 costs the honest reader something: the page cannot say "you are not cleared for this", only that there is
  nothing for them at that id.

## Alternatives

- **Return the excerpt text inside the `/ask` response.** No second endpoint and no second access path. Lost because
  it changes an existing response for every caller, makes every answer several times larger, and still leaves a
  shared link to a source with nothing to load. Would win if sources were only ever read next to their answer.
- **403 for a hidden chunk, 404 for a missing one.** Kinder to the reader. Lost because the difference tells an
  insider that a restricted document with that id exists, which the refusal text in `pipeline.REFUSAL` already takes
  care not to say. Would win in a system where document ids and titles are public and only bodies are protected.
- **Check access in Python and query as a privileged role.** Would allow a real 403. Lost for the reason in ADR 2: the
  guarantee would then depend on this function staying correct.
- **Log excerpt reads with structlog only.** No schema change. Lost because the operations runbook answers "who saw
  this chunk" from the database, and a read that left no row there would make that answer wrong.
