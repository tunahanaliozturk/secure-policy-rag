"""A real Postgres with pgvector: from SPR_TEST_ADMIN_DSN when set (CI's service container), otherwise a container
started here with testcontainers. The schema is migrated and the corpus loaded once per session, with the hashing
embedder so no model download is needed. Tests connect as spr_app, the role the application uses."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

from secure_policy_rag import corpus, store
from secure_policy_rag.embedding import HashingEmbedder

IMAGE = "pgvector/pgvector:0.8.7-pg18-trixie"
APP_PASSWORD = "app-role-test-password"
CORPUS = Path(__file__).parents[2] / "corpus"


@pytest.fixture(scope="session")
def admin_dsn() -> Iterator[str]:
    if dsn := os.environ.get("SPR_TEST_ADMIN_DSN"):
        yield dsn
        return
    from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415  # only when no database is given

    with PostgresContainer(IMAGE, driver=None) as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def app_dsn(admin_dsn: str) -> str:
    parts = urlsplit(admin_dsn)
    host = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit(parts._replace(netloc=f"spr_app:{APP_PASSWORD}@{host}"))


@pytest.fixture(scope="session")
def documents() -> list[corpus.Document]:
    return corpus.load(CORPUS)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_pool(admin_dsn: str, documents: list[corpus.Document]) -> AsyncIterator[asyncpg.Pool]:
    conn = await asyncpg.connect(admin_dsn)
    try:
        await store.migrate(conn, APP_PASSWORD)
        await store.migrate(conn, APP_PASSWORD)  # twice: migrations must be safe to rerun on every deploy
        chunks = [c for d in documents for c in d.chunks()]
        await store.replace_corpus(conn, chunks, HashingEmbedder().embed_passages([c.for_embedding() for c in chunks]))
    finally:
        await conn.close()
    pool = await store.create_pool(admin_dsn, max_size=4)
    yield pool
    await pool.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def app_pool(app_dsn: str, admin_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    pool = await store.create_pool(app_dsn, max_size=8)
    yield pool
    await pool.close()


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()
