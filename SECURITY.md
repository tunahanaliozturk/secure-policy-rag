# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's "Report a vulnerability" button on this repository (private
vulnerability reporting), not in a public issue. Include what you found, how to reproduce it, and what you think the
impact is. You can expect an acknowledgement within a week.

Findings of particular interest:

- any way for a demo user to retrieve a chunk their clearance or departments do not allow;
- any way for personal data in a question or a source to reach the logs, spans, audit log or an answer;
- any way to get an answer past `verify.py` that cites an unretrieved chunk or carries a link to a host outside the
  allow-list;
- any way for the application role to change or delete audit records.

## Scope and known gaps

This is a demonstration system with synthetic data. Known gaps are listed in
[docs/threat-model.md](docs/threat-model.md) and do not need a report: the database trusts the clearance settings the
application sets, names are not detected as personal data, demo tokens cannot be revoked, and a persuasive injection
that produces a false but cited statement is not caught.

## Secrets

The repository contains no secrets. `compose.yaml` uses passwords that are only meant for a local laptop stack and are
named as such; the token secret has no default and must be supplied. If you find a real credential in the history,
report it as above.
