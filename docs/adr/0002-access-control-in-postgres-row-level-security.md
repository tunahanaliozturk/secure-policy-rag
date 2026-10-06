# 2. Access control is enforced by Postgres row-level security

Status: Accepted, 2026-10-06

## Context

Every chunk carries the department that owns it and a classification: public, internal, confidential or restricted.
The rule is short. Public and internal text is open to anyone cleared to that level. Confidential and restricted text
is open only to the owning department, and only with enough clearance. The usual way to apply it is a `WHERE` clause
in the retrieval query. That is one forgotten clause, one new query, or one refactor away from a leak, and in a RAG
system a leak is silent: the model simply has more to quote.

## Decision

Postgres applies the rule. `chunks` has row-level security enabled and forced, with one `SELECT` policy for the
application role `spr_app`. The policy reads the reader's clearance and departments from two settings that the
application sets with `set_config(..., true)` at the start of each retrieval transaction, from a verified token.
`spr_app` owns no table, has no `BYPASSRLS`, and holds two grants: `SELECT` on `chunks` and a column-limited `INSERT`
on `audit_log`. Schema changes and ingestion run as a separate administrator role.

## Consequences

- A retrieval query with no filter at all still returns only permitted rows. The integration tests prove it for each
  demo user against a separate Python statement of the same rule
  (`test_each_reader_sees_exactly_the_chunks_the_access_rule_allows`), and prove the app role cannot disable, drop or
  rewrite the policy, or switch to the administrator role.
- Unset settings mean no clearance and no departments, so forgetting to say who is asking returns nothing.
- Settings are transaction-local, so a pooled connection carries nothing to the next request (tested).
- The settings are trusted input. Code running as `spr_app` can call `set_config` with any value, so a SQL injection
  in the application could raise its own clearance. The defences are parameterised SQL everywhere and departments
  validated against a fixed list before they reach the database. A test documents this gap rather than hiding it.
- An approximate vector index under a row filter can return fewer rows than asked for. With 149 chunks the vector
  search is an exact scan instead, which is correct and fast at this size (docs/operations.md).
- Two roles and two connection strings to operate.

## Alternatives

- **Filter in the application.** Simpler, one role. Lost because the guarantee then depends on every future query.
  Would win only if the database could not be trusted to run policies, which is not the case for Postgres 18.
- **One schema or database per department.** Strong isolation, but text visible to several audiences (everything
  internal) would be copied, and cross-department questions become queries across databases. Would win with hard
  regulatory separation between legal entities.
- **A `SECURITY DEFINER` function that verifies a signed token inside Postgres.** Closes the trusted-settings gap.
  Lost on complexity for this repository; it is the next step if the application tier is not trusted.
