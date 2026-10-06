"""Reciprocal rank fusion: score each item by the sum of ``1 / (k + rank)`` over every ranked list it appears in.

It looks only at ranks, never at raw scores. A full-text rank and a cosine distance are on no common scale, and
normalising one against the other is where hybrid search usually goes quietly wrong. ``k`` damps the gap between the
top few places; 60 is the value from the original paper (Cormack, Clarke and Buettcher, 2009).
"""

from collections.abc import Hashable, Mapping, Sequence


def reciprocal_rank_fusion[K: Hashable](rankings: Mapping[str, Sequence[K]], k: int = 60) -> list[K]:
    """Fused order, best first. Ties keep the order in which items were first seen, so the output is stable."""
    scores: dict[K, float] = {}
    for ranking in rankings.values():
        for position, key in enumerate(dict.fromkeys(ranking), start=1):  # a repeat earns credit once
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
    return sorted(scores, key=lambda key: -scores[key])
