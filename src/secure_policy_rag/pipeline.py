"""One question, start to finish: redact, retrieve, generate, verify, redact again, audit. And one excerpt, opened.

A plain sequence of awaited steps rather than an agent graph (ADR 0006). The flow has no loops and no model-chosen
branches: the model is called at most once and holds no tools. Every exit path writes exactly one audit record, and
an answer is only returned after its audit record is committed, so there is no answer the audit trail does not know.
"""

import asyncio
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field, replace
from typing import Literal

import asyncpg
import structlog
from opentelemetry import trace

from secure_policy_rag import pii, prompt, store, verify
from secure_policy_rag.embedding import Embedder
from secure_policy_rag.identity import Identity
from secure_policy_rag.model import AnswerModel, Generation
from secure_policy_rag.telemetry import tracer

type Outcome = Literal["answered", "refused", "blocked", "model_refused", "error"]

# The refusal does not say whether a better-cleared colleague would get an answer: that would reveal that a
# restricted document on the subject exists.
REFUSAL = "I can't answer that from the policies available to you."
BLOCKED = "I could not produce an answer that passes the source checks, so I am not showing one."

log = structlog.get_logger()


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    title: str
    section: str


@dataclass(frozen=True)
class Answer:
    outcome: Outcome
    text: str
    citations: tuple[Citation, ...] = ()
    redactions: dict[str, int] = field(default_factory=dict)
    """What was removed from the question before anything else saw it."""
    excerpts: tuple[prompt.Excerpt, ...] = ()
    """What retrieval returned for this reader. For the evaluation harness; the API does not send it back."""


class Assistant:
    def __init__(
        self,
        pool: asyncpg.Pool,
        embedder: Embedder,
        model: AnswerModel,
        allowed_link_hosts: Collection[str],
        *,
        k: int = 5,
        retrievers: frozenset[store.Retriever] = frozenset({"lexical", "vector"}),
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._pool = pool
        self._embedder = embedder
        self._model = model
        self._allowed_link_hosts = allowed_link_hosts
        self._k = k
        self._retrievers = retrievers
        self._clock = clock

    async def ask(self, reader: Identity, question: str) -> Answer:
        started = self._clock()
        # Spans carry ids, counts and outcomes, not the subject: traces reach more people than the audit log does.
        with tracer.start_as_current_span("ask") as span:
            span.set_attribute("spr.clearance", reader.clearance.label)
            with tracer.start_as_current_span("redact.question") as s:
                asked = pii.redact(question)
                s.set_attribute("spr.redactions", asked.total)

            audit = _Audit(reader, asked, (), self._model.name)
            try:
                with tracer.start_as_current_span("retrieve") as s:
                    vector = await asyncio.to_thread(self._embedder.embed_query, asked.text)
                    excerpts = tuple(
                        await store.retrieve(
                            self._pool, reader, asked.text, vector, k=self._k, retrievers=self._retrievers
                        )
                    )
                    s.set_attribute("spr.chunk_ids", [e.chunk_id for e in excerpts])
            except Exception:
                await self._finish(audit.done("error", ""), started)
                raise
            audit.excerpts = excerpts
            if not excerpts:
                return await self._finish(audit.done("refused", REFUSAL), started)

            try:
                with tracer.start_as_current_span("generate") as s:
                    generation = await self._model.generate(prompt.build(asked.text, excerpts))
                    s.set_attribute("spr.model", generation.model)
            except Exception:
                await self._finish(audit.done("error", ""), started)
                raise
            audit.generation = generation

            draft = generation.draft
            if draft is None:
                return await self._finish(audit.done("model_refused", REFUSAL), started)
            if draft.status == "insufficient_context":
                return await self._finish(audit.done("refused", REFUSAL), started)

            with tracer.start_as_current_span("verify") as s:
                verdict = verify.check(draft.answer, {e.chunk_id: e.text for e in excerpts}, self._allowed_link_hosts)
                # A reason can quote a host the model wrote, and the model can write personal data into a host.
                violations = tuple(pii.redact(v).text for v in verdict.violations)
                s.set_attribute("spr.violations", list(violations))
            audit.cited, audit.violations = verdict.cited, violations
            if not verdict.ok:
                return await self._finish(audit.done("blocked", BLOCKED), started)
            return await self._finish(audit.done("answered", draft.answer), started)

    async def excerpt(self, reader: Identity, chunk_id: str) -> store.Passage | None:
        """One chunk as this reader may read it, or ``None``. Read through the same row-level security as retrieval,
        held to the rules an answer is held to, and recorded before it is returned: found, not found, or a read that
        failed. An excerpt must not show more than an answer citing it could."""
        with tracer.start_as_current_span("excerpt") as span:
            span.set_attribute("spr.clearance", reader.clearance.label)
            try:
                passage = await store.read(self._pool, reader, chunk_id)
            except Exception:
                await self._read(span, reader, chunk_id, "error")
                raise
            await self._read(span, reader, chunk_id, "not_found" if passage is None else "found")
            if passage is None:
                return None
            # A source can hold a worked example with a customer's IBAN, and a poisoned source a link to a foreign
            # host. An answer is redacted for the first and blocked for the second (verify.py); so is this.
            text = verify.withhold_links(pii.redact(passage.text).text, self._allowed_link_hosts)
            return replace(passage, text=text)

    async def _read(self, span: trace.Span, reader: Identity, chunk_id: str, outcome: store.ReadOutcome) -> None:
        span.set_attribute("spr.outcome", outcome)
        await store.record_read(self._pool, reader, chunk_id, outcome)
        log.info("excerpt", subject=reader.subject, chunk_id=chunk_id, outcome=outcome)

    async def _finish(self, audit: _Audit, started: float) -> Answer:
        # Sources can hold personal data (a worked example with a customer's IBAN), and the model may repeat it.
        with tracer.start_as_current_span("redact.answer") as s:
            shown = pii.redact(audit.text)
            s.set_attribute("spr.redactions", shown.total)
        latency_ms = round((self._clock() - started) * 1000)
        trace.get_current_span().set_attribute("spr.outcome", audit.outcome)
        await store.record(self._pool, audit.entry(shown.counts, latency_ms))
        log.info(
            "ask",
            subject=audit.reader.subject,
            outcome=audit.outcome,
            retrieved=len(audit.excerpts),
            cited=len(audit.cited),
            redactions_in=audit.asked.total,
            redactions_out=shown.total,
            latency_ms=latency_ms,
        )
        by_id = {e.chunk_id: e for e in audit.excerpts}
        cited = audit.cited if audit.outcome == "answered" else ()
        citations = tuple(Citation(c, by_id[c].title, by_id[c].heading) for c in cited)
        return Answer(audit.outcome, shown.text, citations, audit.asked.counts, audit.excerpts)


@dataclass
class _Audit:
    """Collects what the audit record needs as the request moves along, so no exit path can forget a field."""

    reader: Identity
    asked: pii.Redacted
    excerpts: tuple[prompt.Excerpt, ...]
    model: str
    generation: Generation | None = None
    cited: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()
    outcome: Outcome = "error"
    text: str = ""

    def done(self, outcome: Outcome, text: str) -> _Audit:
        self.outcome, self.text = outcome, text
        return self

    def entry(self, redactions_out: dict[str, int], latency_ms: int) -> store.AuditEntry:
        g = self.generation
        return store.AuditEntry(
            subject=self.reader.subject,
            departments=tuple(sorted(self.reader.departments)),
            clearance=self.reader.clearance.label,
            question_redacted=self.asked.text,
            outcome=self.outcome,
            retrieved_chunk_ids=tuple(e.chunk_id for e in self.excerpts),
            cited_chunk_ids=self.cited if self.outcome == "answered" else (),
            redactions_in=self.asked.counts,
            redactions_out=redactions_out,
            violations=self.violations,
            model=g.model if g else self.model,
            latency_ms=latency_ms,
            input_tokens=g.input_tokens if g else None,
            output_tokens=g.output_tokens if g else None,
        )
