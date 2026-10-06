# 7. Hybrid retrieval with plain RRF, kept although vector search alone scored higher here

Status: Accepted, 2026-10-06

## Context

Retrieval combines a Postgres full-text ranking (the question's stemmed words, OR-ed) with an exact cosine ranking from
bge-small-en-v1.5, fused by reciprocal rank fusion with k = 60 and equal weights, the values from the original paper.
On the 56 answerable questions in `eval/retrieval.jsonl` (docs/evaluation.md has the full run):

| Retrieval | recall@5 | nDCG@5 |
|---|---|---|
| Hybrid (RRF, k = 60) | 0.982 | 0.937 |
| Full text only | 0.929 | 0.881 |
| Vector only | 1.000 | 1.000 |

Vector search alone was better on every measure. Down-weighting the full-text list to 0.25 moved hybrid nDCG@5 to 0.960
with k = 60, or 0.978 with k = 10, still below vector alone.

## Decision

We keep hybrid as the default with the paper's parameters, publish the result above, and make the choice a setting
(`SPR_RETRIEVERS=hybrid|vector|lexical`). We do not adopt the tuned weights.

## Consequences

- The default is measurably worse than the best option on this corpus, by about 6 points of nDCG@5. We accept that
  knowingly, for the reason below, and say so in the README.
- Why keep it: the corpus is 35 short, cleanly written documents whose wording the questions paraphrase, which is the
  case where dense retrieval does best. Real policy libraries are full of exact tokens that small embedding models
  handle poorly: article numbers, product codes, regulation names, abbreviations. This evaluation set has only a
  handful of questions of that kind (r64 to r68), and vector search answered all of them, so it cannot show the
  benefit either way. That is a gap in the set, recorded in docs/evaluation.md, and closing it decides this ADR.
- The tuned weights were chosen by looking at the test set, so their scores are optimistic. Adopting them would need a
  held-out set.
- The CI gate compares hybrid with its own baseline, so switching the default needs a new baseline file.

## Alternatives

- **Vector only by default.** Best measured result today. Would win if a larger, held-out evaluation with exact-token
  questions still showed it ahead.
- **Tuned fusion weights.** Lost on overfitting, as above.
- **A cross-encoder reranker.** Often the largest single gain, at the cost of a second model on the request path. Not
  tried; next once the evaluation set is larger.
