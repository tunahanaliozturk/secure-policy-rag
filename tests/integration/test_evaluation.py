"""Both evaluation sets run end to end against the database. With the hashing embedder the relevance numbers mean
little, but leaks and guard failures do not depend on the embedder, so these assertions are exact."""

from pathlib import Path

import asyncpg
import pytest

from secure_policy_rag import corpus, evaluation
from secure_policy_rag.embedding import HashingEmbedder

pytestmark = pytest.mark.asyncio(loop_scope="session")

EVAL = Path(__file__).parents[2] / "eval"


async def test_no_retrieval_case_returns_a_chunk_the_reader_may_not_see(
    app_pool: asyncpg.Pool, documents: list[corpus.Document]
) -> None:
    cases = evaluation.load_cases(EVAL / "retrieval.jsonl", evaluation.RetrievalCase)
    report = await evaluation.evaluate_retrieval(app_pool, HashingEmbedder(), documents, cases)
    assert report.leaks == []
    assert report.cases == len(cases) >= 40


async def test_every_answer_case_passes_its_deterministic_graders_with_the_scripted_model(
    app_pool: asyncpg.Pool, documents: list[corpus.Document]
) -> None:
    cases = evaluation.load_cases(EVAL / "answers.jsonl", evaluation.AnswerCase)
    results = await evaluation.evaluate_answers(
        app_pool, HashingEmbedder(), documents, cases, real_model=None, allowed_hosts={"intranet.bank.example"}
    )
    assert [(r.case, r.failures) for r in results if r.failures] == []
