"""Everything that talks to Postgres: schema, loading the corpus, reading chunks under row-level security, the audit
log and the record of opened excerpts.

Every read of ``chunks`` sets the reader's clearance and departments with ``set_config(..., true)``, which lasts until
the end of the transaction, then queries inside that transaction (:func:`reading_as`). The filtering itself happens in
the database policy (schema.sql). Nothing in this module decides what a user may see; it only says who is asking. A
bug that drops a WHERE clause here still returns only rows the policy allows
(tests/integration/test_access_control.py).
"""

import json
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import asyncpg
from pgvector.asyncpg import register_vector

from secure_policy_rag.corpus import Chunk
from secure_policy_rag.embedding import Vectors
from secure_policy_rag.fusion import reciprocal_rank_fusion
from secure_policy_rag.identity import Identity
from secure_policy_rag.prompt import Excerpt

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

# The query becomes an OR of its stemmed words. plainto_tsquery ANDs them, which suits a search box and not a
# question: "how long do we keep call recordings" should not require the word "keep".
_LEXICAL = (
    "select c.id from chunks c,"
    " (select replace(plainto_tsquery('english', $1)::text, ' & ', ' | ')::tsquery as q) as query"
    " where c.tsv @@ query.q order by ts_rank(c.tsv, query.q, 1) desc, c.id limit $2"
)
_VECTOR = "select id from chunks order by embedding <=> $1, id limit $2"
_HAS_WORD = re.compile(r"\w")


async def migrate(conn: asyncpg.Connection, app_password: str) -> None:
    """Run as the administrator. Creates or updates the schema, policies and grants, and sets spr_app's password."""
    await conn.execute(SCHEMA)
    # DDL takes no bind parameters, so the password is quoted by the server's own quote_literal.
    literal = await conn.fetchval("select quote_literal($1)", app_password)
    await conn.execute(f"alter role spr_app password {literal}")


async def create_pool(dsn: str, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    async def init(conn: asyncpg.Connection) -> None:
        await register_vector(conn)

    pool: asyncpg.Pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size, init=init)
    return pool


async def replace_corpus(conn: asyncpg.Connection, chunks: Sequence[Chunk], vectors: Vectors) -> None:
    """Run as the administrator: the application role cannot write chunks. One transaction, so readers see the old
    corpus or the new one, never half of each."""
    # ponytail: full reload on every ingest; incremental upserts when the corpus outgrows a few seconds of embedding.
    await register_vector(conn)
    async with conn.transaction():
        await conn.execute("delete from chunks")
        await conn.executemany(
            "insert into chunks (id, document_id, title, heading, text, department, classification, embedding)"
            " values ($1, $2, $3, $4, $5, $6, $7, $8)",
            [
                (c.id, c.document_id, c.title, c.heading, c.text, c.department, c.classification.label, v)
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )


type Retriever = Literal["lexical", "vector"]


async def retrieve(
    pool: asyncpg.Pool,
    reader: Identity,
    query: str,
    embedding: Vectors,
    *,
    k: int = 5,
    candidates: int = 30,
    retrievers: frozenset[Retriever] = frozenset({"lexical", "vector"}),
) -> list[Excerpt]:
    """The best ``k`` chunks this reader may see, by reciprocal rank fusion of full-text and vector rankings.
    ``retrievers`` exists so the evaluation can measure each one alone."""
    rankings: dict[str, list[str]] = {}
    async with reading_as(pool, reader) as conn:
        if "lexical" in retrievers and _HAS_WORD.search(query):
            rankings["lexical"] = [r["id"] for r in await conn.fetch(_LEXICAL, query, candidates)]
        if "vector" in retrievers:
            rankings["vector"] = [r["id"] for r in await conn.fetch(_VECTOR, embedding, candidates)]
        winners = reciprocal_rank_fusion(rankings)[:k]
        rows = await conn.fetch(
            "select id, document_id, title, heading, text, classification from chunks where id = any($1::text[])",
            winners,
        )
    by_id = {r["id"]: r for r in rows}
    return [
        Excerpt(
            chunk_id=chunk_id,
            document_id=by_id[chunk_id]["document_id"],
            title=by_id[chunk_id]["title"],
            heading=by_id[chunk_id]["heading"],
            text=by_id[chunk_id]["text"],
            classification=by_id[chunk_id]["classification"],
        )
        for chunk_id in winners
    ]


@dataclass(frozen=True)
class Passage:
    """One chunk as a reader opens it. Unlike an :class:`Excerpt` it says which department owns the text."""

    chunk_id: str
    title: str
    heading: str
    text: str
    department: str
    classification: str


async def read(pool: asyncpg.Pool, reader: Identity, chunk_id: str) -> Passage | None:
    """The chunk with this id, if the policy shows it to this reader. ``None`` covers both "no such chunk" and "not
    for this reader": the query returns no row either way, so nothing above this function can tell them apart or
    reveal which it was (ADR 0009)."""
    async with reading_as(pool, reader) as conn:
        row = await conn.fetchrow(
            "select id, title, heading, text, department, classification from chunks where id = $1", chunk_id
        )
    if row is None:
        return None
    return Passage(row["id"], row["title"], row["heading"], row["text"], row["department"], row["classification"])


@asynccontextmanager
async def reading_as(pool: asyncpg.Pool, reader: Identity) -> AsyncIterator[asyncpg.Connection]:
    """A connection that reads chunks as ``reader`` and as nobody else: a read-only transaction with the reader set.
    Retrieval and single-chunk reads both go through here, so there is one way to say who is asking."""
    async with pool.acquire() as conn, conn.transaction(readonly=True):
        await set_reader(conn, reader)
        yield conn


async def set_reader(conn: asyncpg.Connection, reader: Identity) -> None:
    """Transaction-local: must run inside a transaction, and ends with it, so a pooled connection carries nothing over.
    Department names are validated against a fixed list when the token is verified, so none contains a comma."""
    await conn.execute(
        "select set_config('spr.clearance', $1, true), set_config('spr.departments', $2, true)",
        str(int(reader.clearance)),
        ",".join(sorted(reader.departments)),
    )


@dataclass(frozen=True)
class AuditEntry:
    subject: str
    departments: tuple[str, ...]
    clearance: str
    question_redacted: str
    outcome: str
    retrieved_chunk_ids: tuple[str, ...]
    cited_chunk_ids: tuple[str, ...]
    redactions_in: dict[str, int]
    redactions_out: dict[str, int]
    violations: tuple[str, ...]
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None


async def record(pool: asyncpg.Pool, entry: AuditEntry) -> None:
    # No RETURNING: the application role has no SELECT on audit_log, by design.
    await pool.execute(
        "insert into audit_log (subject, departments, clearance, question_redacted, outcome, retrieved_chunk_ids,"
        " cited_chunk_ids, redactions_in, redactions_out, violations, model, latency_ms, input_tokens, output_tokens)"
        " values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12, $13, $14)",
        entry.subject,
        list(entry.departments),
        entry.clearance,
        entry.question_redacted,
        entry.outcome,
        list(entry.retrieved_chunk_ids),
        list(entry.cited_chunk_ids),
        json.dumps(entry.redactions_in),
        json.dumps(entry.redactions_out),
        list(entry.violations),
        entry.model,
        entry.latency_ms,
        entry.input_tokens,
        entry.output_tokens,
    )


type ReadOutcome = Literal["found", "not_found", "error"]


async def record_read(pool: asyncpg.Pool, reader: Identity, chunk_id: str, outcome: ReadOutcome) -> None:
    """One row per excerpt request that reached the database: who asked for which chunk, and whether the policy
    showed it to them, showed them nothing, or the read failed. A request stopped earlier (no valid token, an id that
    is not shaped like one, the rate limit) never gets here and leaves no row. Insert-only for the application, like
    the audit log."""
    await pool.execute(
        "insert into excerpt_log (subject, departments, clearance, chunk_id, outcome) values ($1, $2, $3, $4, $5)",
        reader.subject,
        sorted(reader.departments),
        reader.clearance.label,
        chunk_id,
        outcome,
    )
