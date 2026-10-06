# 6. A plain async pipeline, not LangGraph

Status: Accepted, 2026-10-06

## Context

The flow is: redact the question, retrieve as the reader, call the model once, verify, redact the answer, write the
audit record. There are no loops, no tool calls and no branch chosen by the model. Every exit must write exactly one
audit record, and no answer may leave before its record is committed.

## Decision

`pipeline.Assistant.ask` is a sequence of awaited steps in one function, with an OpenTelemetry span around each step.
We call Claude through the official `anthropic` SDK directly, not through `langchain-anthropic`.

## Consequences

- The control flow, including every early exit and its audit record, fits on one screen. A reviewer can check "every
  path audits" by reading, and `tests/integration/test_pipeline.py` checks it by running each path.
- Two fewer frameworks in the dependency tree and in the licence audit.
- Adding a retry with a correction, or a second retrieval round, means writing that loop by hand. If the flow grows
  real branching or human approval steps, a graph framework starts to pay for itself.

## Alternatives

- **LangGraph.** Good for multi-step agents with checkpoints and human approval. Lost because none of that exists here,
  and a graph would spread the audit guarantee across nodes and edges.
- **langchain-anthropic.** Convenient structured-output helpers. Lost because the raw SDK call is short, typed, and
  shows exactly what is sent: no temperature, no forced tool choice, a JSON schema in `output_config`. Current Claude
  models reject the first two with a 400, so a reader checking the request benefits from seeing it plainly.
