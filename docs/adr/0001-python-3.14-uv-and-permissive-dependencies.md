# 1. Python 3.14, uv, and permissive licences only

Status: Accepted, 2026-10-06

## Context

The repository is a public portfolio piece aimed at banks. A bank's open-source review rejects copyleft and commercial
licences at any depth, and a reviewer expects current versions. Python 3.14 is the current CPython. The compiled
dependencies this design needs are asyncpg, numpy and onnxruntime; each was checked on PyPI on 2026-10-06 for a cp314
wheel, and each has one (asyncpg 0.31.0, numpy 2.5.3, onnxruntime 1.30.0).

## Decision

We target Python 3.14 only, manage everything with uv (`uv.lock` committed, `uv sync --locked` in CI), and fail the
build on any distribution whose licence is not on a permissive allow list (`tools/license_audit.py`). We use asyncpg
rather than psycopg, because psycopg is LGPL.

## Consequences

- The audit reads installed metadata, so it works offline and sees transitive dependencies: every distribution in the
  locked development environment passes, at the time of writing.
- Anyone on Python 3.13 or older cannot install the package. For a service shipped as a container image that costs
  nothing; for a library it would.
- asyncpg has no type stubs, so mypy treats it as `Any` at the edges of `store.py`. The SQL itself is covered by the
  integration tests instead.

## Alternatives

- **Python 3.13.** Would widen compatibility. Lost because no dependency forced it; it would win if a needed package
  had no 3.14 wheel.
- **psycopg 3.** Better typing and server-side cursors. Lost on its LGPL licence alone.
