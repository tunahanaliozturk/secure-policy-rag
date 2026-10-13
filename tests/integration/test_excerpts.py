"""``GET /excerpts/{chunk_id}``: one chunk, read as the caller through the same row-level security as retrieval.

The claim under test is that a chunk the caller may not read and a chunk that does not exist are one answer, byte for
byte, because they are one answer in the database: the query returns no row either way and the code cannot tell which.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest
import pytest_asyncio
from structlog.testing import capture_logs

from secure_policy_rag import corpus, identity, store
from secure_policy_rag.api import RateLimiter, Services, create_app
from secure_policy_rag.embedding import HashingEmbedder
from secure_policy_rag.identity import DEMO_IDENTITIES, can_read
from secure_policy_rag.model import ScriptedModel
from secure_policy_rag.pipeline import Assistant

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"s" * 32
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
RUNBOOK = "SEC-004#2"  # security, restricted: the crown jewel systems
NOWHERE = "SEC-999#2"  # well formed, and in no corpus
WORKED_EXAMPLE = "KYC-001#4"  # compliance, internal: holds a fake customer's national id, IBAN and phone number


def token(subject: str, ttl: timedelta = timedelta(minutes=5)) -> dict[str, str]:
    return {"Authorization": f"Bearer {identity.issue(DEMO_IDENTITIES[subject], SECRET, NOW, ttl)}"}


def path(chunk_id: str) -> str:
    return f"/excerpts/{chunk_id.replace('#', '%23')}"


def client_for(app_pool: asyncpg.Pool, per_minute: int, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    services = Services(Assistant(app_pool, HashingEmbedder(), ScriptedModel(), {"intranet.bank.example"}), app_pool)

    @asynccontextmanager
    async def unused() -> AsyncIterator[Services]:
        yield services

    app = create_app(unused, [SECRET], RateLimiter(per_minute=per_minute), now=lambda: NOW)
    app.state.services = services
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture(loop_scope="session")
async def client(app_pool: asyncpg.Pool) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(app_pool, per_minute=1000) as c:
        yield c


async def reads(admin_pool: asyncpg.Pool, subject: str) -> list[tuple[str, str]]:
    rows = await admin_pool.fetch("select chunk_id, outcome from excerpt_log where subject = $1 order by id", subject)
    return [(r["chunk_id"], r["outcome"]) for r in rows]


async def test_a_reader_cleared_for_a_chunk_gets_its_text_and_its_labels(client: httpx.AsyncClient) -> None:
    response = await client.get(path(RUNBOOK), headers=token("erin"))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"chunk_id", "title", "section", "text", "classification", "department"}
    assert (body["chunk_id"], body["section"]) == (RUNBOOK, "2. Crown jewel systems")
    assert (body["classification"], body["department"]) == ("restricted", "security")
    assert body["text"].startswith("The crown jewel systems are the payments hub")


@pytest.mark.parametrize("subject", sorted(DEMO_IDENTITIES))
async def test_a_restricted_chunk_the_caller_may_not_read_is_the_same_404_as_a_chunk_that_does_not_exist(
    client: httpx.AsyncClient, documents: list[corpus.Document], subject: str
) -> None:
    runbook = next(d for d in documents if d.id == "SEC-004")
    allowed = can_read(DEMO_IDENTITIES[subject], runbook.classification, runbook.department)
    assert allowed == (subject == "erin"), "the fixture changed: only erin is in security with restricted clearance"

    hidden = await client.get(path(RUNBOOK), headers=token(subject))
    absent = await client.get(path(NOWHERE), headers=token(subject))

    assert absent.status_code == 404
    if allowed:
        assert hidden.status_code == 200
        return
    assert (hidden.status_code, hidden.content, dict(hidden.headers)) == (
        absent.status_code,
        absent.content,
        dict(absent.headers),
    )
    assert b"SEC-004" not in hidden.content
    assert b"crown" not in hidden.content.lower()


async def test_every_reader_can_open_exactly_the_chunks_the_access_rule_allows(
    app_pool: asyncpg.Pool, documents: list[corpus.Document]
) -> None:
    # The store function the endpoint calls, against the Python oracle, for all six readers and every chunk.
    for subject, reader in DEMO_IDENTITIES.items():
        for document in documents:
            expected = can_read(reader, document.classification, document.department)
            for chunk in document.chunks():
                found = await store.read(app_pool, reader, chunk.id)
                assert (found is not None) == expected, f"{subject} reading {chunk.id}"


async def test_personal_data_in_a_source_is_redacted_in_the_excerpt_as_it_is_in_an_answer(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(path(WORKED_EXAMPLE), headers=token("bob"))
    assert response.status_code == 200
    text = response.json()["text"]
    for sentinel in ["10000000146", "TR33 0006 1005 1978 6457 8413 26", "+90 532 123 45 67"]:
        assert sentinel not in text
    assert "[TCKN_1]" in text
    assert "[IBAN_1]" in text
    assert "[PHONE_1]" in text


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer "}, token("erin", ttl=timedelta(seconds=-1))],
    ids=["missing", "empty", "expired"],
)
async def test_an_excerpt_request_without_a_valid_token_is_refused_before_anything_is_read(
    client: httpx.AsyncClient, admin_pool: asyncpg.Pool, headers: dict[str, str]
) -> None:
    before = await admin_pool.fetchval("select count(*) from excerpt_log")
    response = await client.get(path(RUNBOOK), headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert await admin_pool.fetchval("select count(*) from excerpt_log") == before


@pytest.mark.parametrize(
    "chunk_id",
    [
        "NL91ABNA0417164300",
        "sec-004%232",
        "SEC-004",
        "SEC-004%232%20or%201=1",
        "SEC-0004%232",
        "X-001%231",
        "SEC-\u0660\u0660\u0664%23\u0662",  # Arabic-Indic digits: a digit to \\d, not to this pattern
        "SEC-\uff10\uff10\uff14%23\uff12",  # full-width digits, the same
    ],
)
async def test_an_id_that_is_not_shaped_like_a_chunk_id_is_rejected_and_reaches_no_log_or_record(
    client: httpx.AsyncClient, admin_pool: asyncpg.Pool, chunk_id: str
) -> None:
    # The id is caller-chosen text that would otherwise be written to the log and the read record as it came.
    before = await admin_pool.fetchval("select count(*) from excerpt_log")
    with capture_logs() as logs:
        response = await client.get(f"/excerpts/{chunk_id}", headers=token("erin"))
    assert response.status_code == 422
    assert logs == []
    assert await admin_pool.fetchval("select count(*) from excerpt_log") == before


async def test_every_excerpt_request_is_recorded_and_logged_with_ids_only_the_refused_ones_too(
    client: httpx.AsyncClient, admin_pool: asyncpg.Pool
) -> None:
    before = await reads(admin_pool, "carol")
    with capture_logs() as logs:
        await client.get(path(RUNBOOK), headers=token("carol"))
        await client.get(path("HR-001#1"), headers=token("carol"))

    assert (await reads(admin_pool, "carol"))[len(before) :] == [(RUNBOOK, "not_found"), ("HR-001#1", "found")]
    row = await admin_pool.fetchrow("select * from excerpt_log where subject = 'carol' order by id desc limit 1")
    assert (row["departments"], row["clearance"]) == (["hr"], "confidential")
    events = [{k: v for k, v in entry.items() if k != "log_level"} for entry in logs]
    assert events == [
        {"event": "excerpt", "subject": "carol", "chunk_id": RUNBOOK, "outcome": "not_found"},
        {"event": "excerpt", "subject": "carol", "chunk_id": "HR-001#1", "outcome": "found"},
    ]


async def test_excerpt_requests_and_questions_share_one_rate_limit_per_subject(app_pool: asyncpg.Pool) -> None:
    async with client_for(app_pool, per_minute=3) as client:
        asked = await client.post("/ask", json={"question": "How long must my password be?"}, headers=token("dave"))
        codes = [(await client.get(path("HR-001#1"), headers=token("dave"))).status_code for _ in range(3)]
        limited = await client.get(path("HR-001#1"), headers=token("dave"))
        other = await client.get(path("HR-001#1"), headers=token("frank"))

    assert (asked.status_code, codes) == (200, [200, 200, 429])
    assert int(limited.headers["retry-after"]) >= 1
    assert other.status_code == 200


@pytest.mark.parametrize(
    "statement",
    [
        "select * from excerpt_log",
        "update excerpt_log set outcome = 'found'",
        "delete from excerpt_log",
        "truncate excerpt_log",
        "insert into excerpt_log (at, subject, departments, clearance, chunk_id, outcome)"
        " values ('2020-01-01', 'x', '{}', 'public', 'HR-001#1', 'found')",
    ],
)
async def test_the_application_cannot_read_change_delete_or_backdate_excerpt_records(
    app_pool: asyncpg.Pool, statement: str
) -> None:
    async with app_pool.acquire() as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(statement)


async def test_a_link_a_poisoned_source_plants_is_withheld_from_the_excerpt_as_it_is_from_an_answer(
    client: httpx.AsyncClient, documents: list[corpus.Document]
) -> None:
    chunks = [c for d in documents if d.id == "HR-007" for c in d.chunks()]
    poisoned = next(c for c in chunks if "travel-bank-portal.example.net" in c.text)
    honest = next(c for c in chunks if "https://intranet.bank.example/travel" in c.text)

    shown = (await client.get(path(poisoned.id), headers=token("dave"))).json()["text"]
    kept = (await client.get(path(honest.id), headers=token("dave"))).json()["text"]

    assert "travel-bank-portal" not in shown
    assert "[link removed]" in shown
    assert "https://intranet.bank.example/travel" in kept  # a link to an allowed host is shown as written


async def test_a_read_that_fails_in_the_database_is_recorded_as_an_error_and_answered_503(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise asyncpg.PostgresConnectionError("the connection was lost")

    monkeypatch.setattr(store, "read", broken)
    before = await reads(admin_pool, "alice")
    async with client_for(app_pool, per_minute=1000, raise_app_exceptions=False) as client:
        with capture_logs() as logs:
            response = await client.get(path("HR-001#1"), headers=token("alice"))

    assert response.status_code == 503
    assert set(response.json()) == {"detail", "reference"}
    assert (await reads(admin_pool, "alice"))[len(before) :] == [("HR-001#1", "error")]
    assert [e["outcome"] for e in logs if e["event"] == "excerpt"] == ["error"]


@pytest.mark.parametrize("url", ["/excerpts/SEC-004%232/", "/ask/", "/healthz/"])
async def test_a_trailing_slash_is_a_404_not_a_redirect_to_an_address_that_lost_the_proxy_prefix(
    client: httpx.AsyncClient, url: str
) -> None:
    # Behind nginx the API is under /api/ on port 8440. A redirect built by the API knows neither.
    response = await client.get(url)
    assert response.status_code == 404
    assert "location" not in response.headers


async def test_the_migration_carries_the_unreleased_found_column_over_to_outcome(
    admin_dsn: str, admin_pool: asyncpg.Pool
) -> None:
    # 0.2.0 was built with excerpt_log.found before it had an outcome. A database from that build is upgraded in
    # place. DDL is transactional in Postgres, so the old shape is staged and rolled back without touching the session.
    conn = await asyncpg.connect(admin_dsn)
    transaction = conn.transaction()
    await transaction.start()
    try:
        await conn.execute(
            "drop table excerpt_log;"
            " create table excerpt_log (id uuid primary key default uuidv7(), at timestamptz not null default now(),"
            " subject text not null, departments text[] not null, clearance text not null, chunk_id text not null,"
            " found boolean not null);"
            " insert into excerpt_log (subject, departments, clearance, chunk_id, found) values"
            " ('old', '{}', 'public', 'HR-001#1', true), ('old', '{}', 'public', 'SEC-004#2', false)"
        )
        await store.migrate(conn, "app-role-test-password")
        await store.migrate(conn, "app-role-test-password")
        rows = await conn.fetch("select chunk_id, outcome from excerpt_log where subject = 'old' order by id")
        columns = await conn.fetch(
            "select column_name from information_schema.columns where table_name = 'excerpt_log'"
        )
    finally:
        await transaction.rollback()
        await conn.close()

    assert [(r["chunk_id"], r["outcome"]) for r in rows] == [("HR-001#1", "found"), ("SEC-004#2", "not_found")]
    assert "found" not in {c["column_name"] for c in columns}
    assert await admin_pool.fetchval("select count(*) from excerpt_log where subject = 'old'") == 0
