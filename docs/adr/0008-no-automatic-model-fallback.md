# 8. No automatic fallback to a different model

Status: Accepted, 2026-10-06

## Context

The Messages API can rerun a request that a model declines on safety grounds on another model, server-side
(`fallbacks: "default"`), and Anthropic's SDK guidance suggests turning that on by default. In a bank, the model that
answers staff questions is a governed component: model risk management validates a specific model, and the audit trail
must say which model produced each answer.

## Decision

We do not enable server-side fallback. A safety refusal (`stop_reason: "refusal"`) becomes a refusal to the user with
outcome `model_refused` in the audit log, and the model id the API reported is recorded either way.

## Consequences

- Every answer comes from the configured, validated model. Changing it is a configuration change that goes through
  whatever approval the bank requires.
- A question the model declines gets no answer where a fallback might have given one. For questions about internal
  policies we expect this to be rare; the audit log counts it, so the expectation can be checked.
- The audit record stores `response.model` rather than the configured name, so it stays correct if fallback is turned
  on later.

## Alternatives

- **`fallbacks: "default"`.** Fewer unanswered questions. Would win where availability matters more than model
  governance, or once the fallback model has been validated too; the audit trail is already ready for it.
