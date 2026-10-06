# Evaluation

Two evaluations, both against a real Postgres with row-level security switched on, so access control is part of what
is measured rather than assumed. Both run in CI on every push (`evaluation` job).

## Retrieval

`eval/retrieval.jsonl` holds 69 questions. Each names the demo user who asks and the documents that answer it for that
user. 56 are answerable. 13 have an empty expected list because the answer exists only in a document that user may
not read; for those, the only thing that counts is that nothing forbidden comes back.

Two kinds of answerable question:

- **r01 to r52, close paraphrase.** Questions in the vocabulary of the policy. Easy; every retriever does well.
- **r53 to r68, written to be harder.** Little word overlap with the policy ("Do I have to change my login secret every
  90 days?" for the password standard), plus a few exact-token lookups (an alert number, an investigation code name, a
  document control code).

For each question and each retriever setting, the harness retrieves the top 5 chunks as that user, turns them into a
document ranking, and scores recall@5 and nDCG@5 with binary relevance. Separately, every chunk returned in any setting
is checked against `identity.can_read`, a Python statement of the access rule written independently of the SQL policy.
One chunk the user should not see fails the run, whatever the averages say.

### Results

Run on 2026-10-06, Intel Core Ultra 7 255H, Windows 11, Postgres 18 with pgvector 0.8.7 in Docker Desktop,
embedding model BAAI/bge-small-en-v1.5 through fastembed 0.8.1 (`uv run spr eval-retrieval`):

| Retrieval | recall@5 | nDCG@5 |
|---|---|---|
| Hybrid, RRF k = 60 (default) | 0.982 | 0.937 |
| Full text only | 0.929 | 0.881 |
| Vector only | 1.000 | 1.000 |

**Leaks: 0 of 69 questions, in all three settings.**

The one hybrid miss is r55, "Do I have to change my login secret every 90 days?": the OR-ed full-text query matches
"90 days" in five other documents, and fusion lets those outvote the vector ranking, which had the password standard
first.

Vector search alone beat hybrid on this set. That is the opposite of what we expected and is published as measured.
ADR 7 explains why hybrid stays the default anyway and what would change that. In short: this corpus is small and
cleanly written, the set has only a handful of exact-token questions (r64 to r68), and vector search answered all of
those too. A larger set with real identifiers, held out from any tuning, decides it.

Sensitivity, for the record and not adopted, because it was measured on the same questions it would be judged on:

| Fusion | recall@5 | nDCG@5 |
|---|---|---|
| k = 60, full-text weight 1.0 (default) | 0.982 | 0.937 |
| k = 60, full-text weight 0.5 | 0.982 | 0.960 |
| k = 10, full-text weight 0.5 | 1.000 | 0.965 |
| k = 10, full-text weight 0.25 | 1.000 | 0.978 |

### The gate

`eval/baseline.json` stores the hybrid scores. CI fails if hybrid recall@5 or nDCG@5 drops more than 0.02 below them,
or if any question leaks. Regenerate the baseline with `spr eval-retrieval --write-baseline` only on purpose, and
commit it with the change that justified it.

## Answers

`eval/answers.jsonl` holds 16 whole-pipeline cases. Each names a user, a question, and a scripted model behaviour:

| Behaviour | What the stand-in model does | What the pipeline must do |
|---|---|---|
| `faithful` | Quotes the first sentence of the best excerpt and cites it | Answer |
| `insufficient` | Says the sources do not cover the question | Refuse |
| `echo` | Copies two excerpts wholesale, personal data and links included | Answer, with personal data redacted |
| `repeat_links` | Passes on every link it saw, as a poisoned page asks | Block if any link is not allowed |
| `cite_unretrieved` | Adds a citation to the restricted runbook | Block |
| `invent_url` | Adds a link no source contains | Block |
| `no_citation` | Answers without citing | Block |

Every case is graded by deterministic graders: the outcome matches; every citation was retrieved for that user; no
control code from a document the user cannot read appears; `pii.find` finds nothing in the final answer; every link
points at an allowed host.

Result, same machine and date: **16 of 16 cases pass** (`uv run spr eval-answers`).

What this does and does not show. It shows that the guards around the model hold when the model misbehaves in these
seven specific ways. It says nothing about how often Claude itself answers correctly, refuses correctly, or resists a
cleverer injection. That needs `ANTHROPIC_API_KEY` and:

```
uv run spr eval-answers --model anthropic --judge
```

With a real model the outcome grader uses each case's `should_answer` field instead of the scripted expectation, and
`--judge` asks the same model, through structured output, whether each answer is supported by its excerpts. **This has
not been run.** There was no API key on the machine this repository was built on, so there are no real-model numbers
here.

## Gaps in the evaluation itself

- 69 retrieval questions and 16 answer cases are enough to catch regressions and leaks, not to estimate quality with
  any precision. A difference of one question moves recall@5 by 0.018.
- Questions were written by the same person who wrote the corpus, which flatters every retriever.
- No questions span two documents in a way that needs both, apart from r50.
- No held-out split, so nothing here can be used to tune parameters honestly.
