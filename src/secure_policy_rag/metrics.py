"""Ranking measures with binary relevance, written out so they can be checked against the textbook definitions."""

import math
from collections.abc import Collection, Sequence


def recall_at_k(ranking: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Share of the relevant documents that appear in the top k."""
    return len(set(relevant).intersection(ranking[:k])) / len(relevant) if relevant else 0.0


def ndcg_at_k(ranking: Sequence[str], relevant: Collection[str], k: int) -> float:
    """DCG of the ranking over DCG of a perfect one. 1.0 puts every relevant document first; 0.0 finds none."""
    dcg = sum(1 / math.log2(i + 2) for i, doc in enumerate(ranking[:k]) if doc in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0
