"""The whole question path against the real database, with scripted models standing in for Claude."""

import json

import asyncpg
import pytest

from secure_policy_rag.embedding import HashingEmbedder, Vectors
from secure_policy_rag.identity import DEMO_IDENTITIES
from secure_policy_rag.model import AnswerModel, Behaviour, Draft, Generation, ScriptedModel
from secure_policy_rag.pipeline import BLOCKED, REFUSAL, Assistant
from secure_policy_rag.prompt import Prompt

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOSTS = {"intranet.bank.example"}


def assistant(pool: asyncpg.Pool, model: AnswerModel) -> Assistant:
    return Assistant(pool, HashingEmbedder(), model, HOSTS)


async def last_audit(admin_pool: asyncpg.Pool, subject: str) -> asyncpg.Record:
    row: asyncpg.Record = await admin_pool.fetchrow(
        "select * from audit_log where subject = $1 order by id desc limit 1", subject
    )
    return row


async def test_a_faithful_answer_is_returned_with_citations_it_was_allowed_to_see(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool
) -> None:
    answer = await assistant(app_pool, ScriptedModel("faithful")).ask(
        DEMO_IDENTITIES["alice"], "What is the maximum debt-to-income ratio for a consumer loan?"
    )
    assert answer.outcome == "answered"
    assert answer.citations
    assert {c.chunk_id for c in answer.citations} <= {e.chunk_id for e in answer.excerpts}
    row = await last_audit(admin_pool, "alice")
    assert row["outcome"] == "answered"
    assert row["cited_chunk_ids"] == [c.chunk_id for c in answer.citations]
    assert row["retrieved_chunk_ids"] == [e.chunk_id for e in answer.excerpts]
    assert row["model"] == "scripted:faithful"


@pytest.mark.parametrize(
    ("behaviour", "violation"),
    [
        ("cite_unretrieved", "unretrieved_citation:SEC-004#1"),
        ("invent_url", "url_not_in_sources:policy-portal.example.net"),
        ("no_citation", "no_citation"),
    ],
)
async def test_an_answer_that_breaks_a_source_rule_is_blocked_and_the_reason_audited(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool, behaviour: Behaviour, violation: str
) -> None:
    answer = await assistant(app_pool, ScriptedModel(behaviour)).ask(
        DEMO_IDENTITIES["dave"], "What are the IT helpdesk opening hours?"
    )
    assert (answer.outcome, answer.text, answer.citations) == ("blocked", BLOCKED, ())
    row = await last_audit(admin_pool, "dave")
    assert row["outcome"] == "blocked"
    assert violation in row["violations"]
    assert row["cited_chunk_ids"] == []


async def test_personal_data_the_model_copies_from_a_source_is_redacted_before_the_user_sees_it(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool
) -> None:
    class CopiesTheWorkedExample:
        name = "copies-example"

        async def generate(self, prompt: Prompt) -> Generation:
            example = next(e for e in prompt.excerpts if e.chunk_id == "KYC-001#4")
            return Generation(Draft(status="answered", answer=f"{example.text} [{example.chunk_id}]"), self.name)

    answer = await assistant(app_pool, CopiesTheWorkedExample()).ask(
        DEMO_IDENTITIES["bob"], "Show me the worked example review of customer Yilmaz with the national id and IBAN"
    )
    assert answer.outcome == "answered"
    assert "10000000146" not in answer.text and "TR33" not in answer.text
    assert "[TCKN_1]" in answer.text
    redacted = json.loads((await last_audit(admin_pool, "bob"))["redactions_out"])
    assert redacted == {"IBAN": 1, "TCKN": 1, "PHONE": 1}


async def test_insufficient_context_becomes_a_refusal_that_does_not_hint_at_hidden_documents(
    app_pool: asyncpg.Pool,
) -> None:
    answer = await assistant(app_pool, ScriptedModel("insufficient")).ask(
        DEMO_IDENTITIES["dave"], "What is the salary range for grade 12?"
    )
    assert (answer.outcome, answer.text) == ("refused", REFUSAL)


async def test_a_safety_refusal_from_the_model_is_a_refusal_with_the_reporting_model_audited(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool
) -> None:
    class Declines:
        name = "declines"

        async def generate(self, prompt: Prompt) -> Generation:
            return Generation(None, "claude-sonnet-5-5", 900, 3)

    answer = await assistant(app_pool, Declines()).ask(DEMO_IDENTITIES["carol"], "How many leave days do I get?")
    assert answer.outcome == "model_refused"
    row = await last_audit(admin_pool, "carol")
    assert (row["outcome"], row["model"], row["input_tokens"], row["output_tokens"]) == (
        "model_refused",
        "claude-sonnet-5-5",
        900,
        3,
    )


async def test_a_model_failure_is_audited_before_the_error_propagates(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool
) -> None:
    class Broken:
        name = "broken"

        async def generate(self, prompt: Prompt) -> Generation:
            raise TimeoutError

    with pytest.raises(TimeoutError):
        await assistant(app_pool, Broken()).ask(DEMO_IDENTITIES["erin"], "How long must my password be?")
    row = await last_audit(admin_pool, "erin")
    assert (row["outcome"], row["model"]) == ("error", "broken")


async def test_personal_data_the_model_puts_in_a_blocked_link_is_redacted_in_the_audited_reasons(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool
) -> None:
    class SmugglesAnIbanInAHost:
        name = "smuggles"

        async def generate(self, prompt: Prompt) -> Generation:
            top = prompt.excerpts[0].chunk_id
            answer = f"See https://nl91abna0417164300.attacker.example/x [{top}]"
            return Generation(Draft(status="answered", answer=answer), self.name)

    answer = await assistant(app_pool, SmugglesAnIbanInAHost()).ask(DEMO_IDENTITIES["dave"], "How do I book travel?")
    assert answer.outcome == "blocked"
    row = await last_audit(admin_pool, "dave")
    assert row["violations"] == ["url_not_in_sources:[IBAN_1].attacker.example"]


async def test_a_retrieval_failure_is_audited_before_the_error_propagates(
    app_pool: asyncpg.Pool, admin_pool: asyncpg.Pool
) -> None:
    class BrokenEmbedder(HashingEmbedder):
        def embed_query(self, text: str) -> Vectors:
            raise RuntimeError

    failing = Assistant(app_pool, BrokenEmbedder(), ScriptedModel(), HOSTS)
    with pytest.raises(RuntimeError):
        await failing.ask(DEMO_IDENTITIES["alice"], "How long must my password be?")
    row = await last_audit(admin_pool, "alice")
    assert (row["outcome"], row["retrieved_chunk_ids"]) == ("error", [])
