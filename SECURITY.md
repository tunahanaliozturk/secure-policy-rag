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
- any way for the application role to change or delete audit records or excerpt records;
- any way to tell, from `GET /excerpts/{chunk_id}`, a chunk that exists but is hidden from the caller apart from a
  chunk that does not exist;
- any way to get a token from the demo login for anyone but the six demo identities, or with a different clearance;
- any way for the browser console to show a person text the API did not return to that person.

## Scope and known gaps

This is a demonstration system with synthetic data. Known gaps are listed in
[docs/threat-model.md](docs/threat-model.md) and do not need a report: the database trusts the clearance settings the
application sets, names are not detected as personal data, demo tokens cannot be revoked, and a persuasive injection
that produces a false but cited statement is not caught.

The demo login (`spr demo-login`, port 8441 in compose, and port 8440 under `/login/` behind the console's nginx)
hands a token to anyone who names one of six people. That is
deliberate and written down in [ADR 10](docs/adr/0010-the-demo-login-is-a-separate-process.md); it is a finding only
if it can be made to do more than that. Do not run it where a stranger can reach it.

## The browser console

The console in `web/` keeps bearer tokens in memory only, renders answers and excerpts as text, and is served with
`Content-Security-Policy: default-src 'self'` on every response, proxied ones included
([ADR 11](docs/adr/0011-browser-console-generated-contract-parsed-responses-one-origin.md)). A way to make it store a
token, render markup from an answer, or load anything from another origin is worth a report.

## Secrets

The repository contains no secrets. `compose.yaml` uses passwords that are only meant for a local laptop stack and are
named as such; the token secret has no default and must be supplied. If you find a real credential in the history,
report it as above.
