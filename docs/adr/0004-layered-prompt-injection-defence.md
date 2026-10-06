# 4. Prompt-injection defence in layers, with no tools for the model

Status: Accepted, 2026-10-06

## Context

Retrieved policy text is written by people, and anyone who can edit a policy page can write to the model. The corpus
includes four poisoned documents that try the common moves: exfiltrate restricted content (SEC-006), replace the
system prompt (HR-006), push a phishing login link (HR-007), and get chunks the reader cannot see cited (DATA-005). No
prompt reliably stops a model from following instructions in its input, so the design cannot depend on the model
behaving.

## Decision

Four layers, each useful when the one before it fails:

1. **Nothing restricted reaches the prompt** unless the reader may see it, because retrieval runs under row-level
   security (ADR 2). An injection cannot exfiltrate what the model was never given.
2. **The model has no tools and no side effects.** It returns one JSON object through native structured output. The
   worst an injection can do is shape the text of the answer.
3. **Retrieved text is fenced as data.** Each excerpt sits in an `<excerpt>` element, every `<`, `>` and `&` is escaped
   so a document cannot close its own element, and the system prompt says instructions inside excerpts are not to be
   followed.
4. **The answer is verified before anyone sees it.** It must cite at least one chunk; every citation must be a chunk
   retrieved for this reader in this request; every link must appear verbatim in a retrieved excerpt and point at an
   allowed host. Any failure blocks the whole answer and is audited with its reason.

## Consequences

- Layers 1, 2 and 4 hold whatever the model does. They are tested with scripted models that misbehave on purpose
  (`eval/answers.jsonl`, `tests/integration/test_pipeline.py`).
- Layer 3 is a request to the model, not a guarantee. An injection that persuades the model to state something false
  in plain text, with a valid citation and no link, passes every check. Only a faithfulness grader would catch that,
  and the one in `evaluation.py` needs an API key and has not been run.
- Blocking whole answers will sometimes block a good answer that cited sloppily. We prefer that to repairing answers in
  code.

## Alternatives

- **An input classifier for injections.** Catches known phrasings, misses new ones, and fires on policies that
  legitimately discuss phishing. Would win as an extra signal for flagging documents at ingestion.
- **Agentic retrieval with a search tool.** Lets the model search again, but gives an injection a tool to call. Lost
  on agency; it would need the same verification plus authorisation on every call.
