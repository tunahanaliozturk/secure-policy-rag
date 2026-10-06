"""The HTTP surface, in-process against the real database. The lifespan hook is skipped: services are attached
directly so the app shares the test session's event loop and connection pool."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest
import pytest_asyncio

from secure_policy_rag import identity
from secure_policy_rag.api import RateLimiter, Services, create_app
from secure_policy_rag.embedding import HashingEmbedder
from secure_policy_rag.identity import DEMO_IDENTITIES
from secure_policy_rag.model import ScriptedModel
from secure_policy_rag.pipeline import Assistant

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"s" * 32
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def token(subject: str, ttl: timedelta = timedelta(minutes=5), secret: bytes = SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {identity.issue(DEMO_IDENTITIES[subject], secret, NOW, ttl)}"}


@pytest_asyncio.fixture(loop_scope="session")
async def client(app_pool: asyncpg.Pool) -> AsyncIterator[httpx.AsyncClient]:
    services = Services(Assistant(app_pool, HashingEmbedder(), ScriptedModel(), {"intranet.bank.example"}), app_pool)

    @asynccontextmanager
    async def unused() -> AsyncIterator[Services]:
        yield services

    app = create_app(unused, [SECRET], RateLimiter(per_minute=3), now=lambda: NOW)
    app.state.services = services
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_a_signed_in_employee_gets_a_cited_answer(client: httpx.AsyncClient) -> None:
    response = await client.post("/ask", json={"question": "How long must my password be?"}, headers=token("dave"))
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answered"
    assert body["citations"]
    assert set(body) == {"outcome", "answer", "citations", "question_redactions"}  # no excerpts, no internals


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic YWxpY2U6c2VjcmV0"},
        token("dave", secret=b"x" * 32),
        token("dave", ttl=timedelta(seconds=-1)),
    ],
    ids=["missing", "empty", "wrong-scheme", "wrong-secret", "expired"],
)
async def test_a_request_without_a_valid_token_is_refused_before_anything_runs(
    client: httpx.AsyncClient, admin_pool: asyncpg.Pool, headers: dict[str, str]
) -> None:
    before = await admin_pool.fetchval("select count(*) from audit_log")
    response = await client.post("/ask", json={"question": "anything"}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert await admin_pool.fetchval("select count(*) from audit_log") == before


async def test_the_rate_limit_applies_per_verified_subject(client: httpx.AsyncClient) -> None:
    question = {"question": "How many days a week can I work from home?"}
    codes = [(await client.post("/ask", json=question, headers=token("frank"))).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    other = await client.post("/ask", json=question, headers=token("carol"))
    assert other.status_code == 200


async def test_a_question_with_unexpected_fields_or_no_text_is_rejected(client: httpx.AsyncClient) -> None:
    for body in [{"question": ""}, {"question": "x", "clearance": "restricted"}, {"question": "x" * 2001}]:
        response = await client.post("/ask", json=body, headers=token("erin"))
        assert response.status_code == 422, body


async def test_health_needs_no_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})
