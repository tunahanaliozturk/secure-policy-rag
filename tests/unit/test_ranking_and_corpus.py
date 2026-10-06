import math
from pathlib import Path

import pytest

from secure_policy_rag import corpus
from secure_policy_rag.api import RateLimiter
from secure_policy_rag.fusion import reciprocal_rank_fusion
from secure_policy_rag.metrics import ndcg_at_k, recall_at_k


def test_fusion_rewards_agreement_between_retrievers() -> None:
    fused = reciprocal_rank_fusion({"lexical": ["a", "b", "c"], "vector": ["d", "b", "e"]}, k=60)
    assert fused[0] == "b"  # second in both beats first in one: 2/62 > 1/61
    assert set(fused) == {"a", "b", "c", "d", "e"}


def test_fusion_counts_a_repeated_item_once_per_list() -> None:
    assert reciprocal_rank_fusion({"x": ["a", "a", "b"]}) == ["a", "b"]


def test_recall_and_ndcg_match_hand_computed_values() -> None:
    ranking = ["x", "a", "y", "b"]
    assert recall_at_k(ranking, ["a", "b"], 2) == 0.5
    assert recall_at_k(ranking, ["a", "b"], 4) == 1.0
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(ranking, ["a", "b"], 4) == pytest.approx(expected)
    assert ndcg_at_k(["a"], ["a"], 5) == 1.0


def test_sections_become_chunks_numbered_by_section() -> None:
    document = corpus.parse(
        "---\nid: HR-099\ntitle: T\ndepartment: hr\nclassification: confidential\n---\n"
        "# T\n\nControl code: CC-HR-099-AAAA\n\n"
        "## 1. First\nOne.\n\n## 2. Second\nTwo\nlines.\n"
    )
    assert [(c.id, c.heading, c.text) for c in document.chunks()] == [
        ("HR-099#0", "Document control", "Control code: CC-HR-099-AAAA"),
        ("HR-099#1", "1. First", "One."),
        ("HR-099#2", "2. Second", "Two lines."),
    ]


@pytest.mark.parametrize(
    "header",
    [
        "id: HR-099\ntitle: T\ndepartment: hr\nclassification: secret",  # not a level
        "id: HR-099\ntitle: T\ndepartment: legal\nclassification: public",  # not a department
        "id: hr99\ntitle: T\ndepartment: hr\nclassification: public",  # not an id
        "id: HR-099\ndepartment: hr\nclassification: public",  # no title
    ],
)
def test_a_document_with_a_bad_header_is_refused_at_load_time(header: str) -> None:
    with pytest.raises(corpus.CorpusError):
        corpus.parse(f"---\n{header}\n---\n## 1. S\ntext\n")


def test_the_shipped_corpus_loads() -> None:
    documents = corpus.load(Path(__file__).parents[2] / "corpus")
    assert len(documents) >= 25
    assert {d.classification.label for d in documents} == {"public", "internal", "confidential", "restricted"}


def test_the_rate_limiter_allows_a_burst_then_refills_over_time() -> None:
    now = [0.0]
    limiter = RateLimiter(per_minute=2, clock=lambda: now[0])
    assert [limiter.retry_after("a"), limiter.retry_after("a")] == [0.0, 0.0]
    assert limiter.retry_after("a") == pytest.approx(30.0)
    assert limiter.retry_after("b") == 0.0  # buckets are per subject
    now[0] = 30.0
    assert limiter.retry_after("a") == 0.0
