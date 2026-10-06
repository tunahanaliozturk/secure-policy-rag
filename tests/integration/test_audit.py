"""The audit log is append-only for the application, and holds no raw personal data from questions or answers."""

import json
from collections.abc import Iterator

import asyncpg
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import capture_logs

from secure_policy_rag import store
from secure_policy_rag.embedding import HashingEmbedder
from secure_policy_rag.identity import DEMO_IDENTITIES
from secure_policy_rag.model import ScriptedModel
from secure_policy_rag.pipeline import Assistant

pytestmark = pytest.mark.asyncio(loop_scope="session")

ENTRY = store.AuditEntry(
    subject="test",
    departments=("hr",),
    clearance="internal",
    question_redacted="q",
    outcome="refused",
    retrieved_chunk_ids=(),
    cited_chunk_ids=(),
    redactions_in={},
    redactions_out={},
    violations=(),
    model="scripted:faithful",
    latency_ms=1,
    input_tokens=None,
    output_tokens=None,
)


@pytest.fixture(scope="session")
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter


async def test_the_application_can_append_an_audit_record(app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool) -> None:
    before = await admin_pool.fetchval("select count(*) from audit_log where subject = 'test'")
    await store.record(app_pool, ENTRY)
    assert await admin_pool.fetchval("select count(*) from audit_log where subject = 'test'") == before + 1


@pytest.mark.parametrize(
    "statement",
    [
        "select * from audit_log",
        "update audit_log set outcome = 'answered'",
        "delete from audit_log",
        "truncate audit_log",
        "insert into audit_log (at, subject, departments, clearance, question_redacted, outcome, retrieved_chunk_ids,"
        " cited_chunk_ids, redactions_in, redactions_out, violations, model, latency_ms)"
        " values ('2020-01-01', 'x', '{}', 'public', 'q', 'refused', '{}', '{}', '{}', '{}', '{}', 'm', 1)",
    ],
)
async def test_the_application_cannot_read_change_delete_or_backdate_audit_records(
    app_pool: asyncpg.Pool, statement: str
) -> None:
    async with app_pool.acquire() as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(statement)


async def test_personal_data_in_a_question_reaches_no_log_span_audit_record_or_answer(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool, spans: InMemorySpanExporter
) -> None:
    sentinels = ["NL91 ABNA 0417 1643 00", "sentinel.person@example.com", "111222333"]
    question = f"My IBAN is {sentinels[0]}, email {sentinels[1]}, BSN {sentinels[2]}. Can I work from home?"
    assistant = Assistant(app_pool, HashingEmbedder(), ScriptedModel("echo"), {"intranet.bank.example"})
    with capture_logs() as logs:
        answer = await assistant.ask(DEMO_IDENTITIES["frank"], question)

    row = await admin_pool.fetchrow("select * from audit_log where subject = 'frank' order by id desc limit 1")
    exported = [str(s.to_json()) for s in spans.get_finished_spans()]
    places = {"answer": answer.text, "audit": str(dict(row)), "logs": str(logs), "spans": " ".join(exported)}
    for sentinel in sentinels:
        for where, text in places.items():
            assert sentinel not in text, f"{sentinel} found in {where}"
    assert row["question_redacted"].startswith("My IBAN is [IBAN_1], email [EMAIL_1], BSN [BSN_1].")
    assert json.loads(row["redactions_in"]) == {"IBAN": 1, "EMAIL": 1, "BSN": 1}
    assert exported, "the span exporter saw nothing, so the span half of this test proved nothing"
