"""HTTP: ``POST /ask`` and ``GET /excerpts/{chunk_id}`` behind a bearer token, and an unauthenticated ``GET /healthz``
for the container probe.

Every route on ``protected`` requires a valid token, so a route added later is authenticated unless someone moves it
out deliberately. The rate limit is keyed on the verified subject, never on anything the caller can choose freely.
This process verifies tokens and never signs one: the demo's tokens come from a separate process (demo_login.py).
"""

import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Annotated, Any

import asyncpg
import structlog
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from secure_policy_rag import identity
from secure_policy_rag.identity import ClearanceLabel, Department, Identity
from secure_policy_rag.pipeline import Assistant, Outcome

log = structlog.get_logger()

# 'CR-001#2': document id and section number (corpus.py). The id in the path is caller-chosen text that ends up in the
# log and the excerpt record, so anything not shaped like an id is refused before either sees it.
CHUNK_ID = r"^[A-Z]{2,5}-\d{3}#\d{1,3}$"


@dataclass(frozen=True)
class Services:
    assistant: Assistant
    pool: asyncpg.Pool


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)


class CitationOut(BaseModel):
    chunk_id: str
    title: str
    section: str


class AskResponse(BaseModel):
    outcome: Outcome
    answer: str
    citations: list[CitationOut]
    question_redactions: dict[str, int]
    """Counts by kind of what was removed from the question before it went anywhere, so the user can see it happened."""


class ExcerptOut(BaseModel):
    chunk_id: str
    title: str
    section: str
    text: str
    """Redacted like an answer: a source can hold personal data, and opening it must not show more than citing it."""
    classification: ClearanceLabel
    department: Department


class Problem(BaseModel):
    detail: str


class Unavailable(BaseModel):
    detail: str
    reference: str
    """An id for this failure. The log line that explains it carries the same id."""


# What a caller can get besides the 200, written down so the generated browser client knows the shapes.
_REFUSALS: dict[int | str, dict[str, Any]] = {
    401: {"model": Problem, "description": "The token is missing, invalid or expired."},
    429: {
        "model": Problem,
        "description": "Too many requests from this subject.",
        "headers": {"Retry-After": {"schema": {"type": "integer"}, "description": "Seconds until the next attempt."}},
    },
    503: {"model": Unavailable, "description": "Something failed. The reference names the log line."},
}


class RateLimiter:
    """Token bucket per subject: ``per_minute`` requests, refilled continuously."""

    # ponytail: in-process state, so each replica has its own buckets; move it to the gateway or Redis past one replica.
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity = float(per_minute)
        self._rate = per_minute / 60.0
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def retry_after(self, subject: str) -> float:
        """0 when the request may go ahead (and is counted), otherwise seconds until the next one would be allowed."""
        now = self._clock()
        tokens, last = self._buckets.get(subject, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - last) * self._rate)
        if tokens < 1:
            self._buckets[subject] = (tokens, now)
            return (1 - tokens) / self._rate
        self._buckets[subject] = (tokens - 1, now)
        return 0.0


def create_app(
    open_services: Callable[[], AbstractAsyncContextManager[Services]],
    token_secrets: list[bytes],
    limiter: RateLimiter,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with open_services() as services:
            app.state.services = services
            yield

    app = FastAPI(title="secure-policy-rag", version=version("secure-policy-rag"), lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def reader(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Identity:
        try:
            if credentials is None:
                raise identity.InvalidToken
            return identity.verify(credentials.credentials, token_secrets, now())
        except identity.InvalidToken:
            raise HTTPException(401, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"}) from None

    def throttle(who: Identity) -> None:
        if (wait := limiter.retry_after(who.subject)) > 0:
            raise HTTPException(429, "too many requests", headers={"Retry-After": str(int(wait) + 1)})

    protected = APIRouter(dependencies=[Depends(reader)])

    @protected.post("/ask", responses=_REFUSALS)
    async def ask(body: AskRequest, request: Request, who: Annotated[Identity, Depends(reader)]) -> AskResponse:
        throttle(who)
        services: Services = request.app.state.services
        answer = await services.assistant.ask(who, body.question)
        return AskResponse(
            outcome=answer.outcome,
            answer=answer.text,
            citations=[CitationOut(chunk_id=c.chunk_id, title=c.title, section=c.section) for c in answer.citations],
            question_redactions=answer.redactions,
        )

    @protected.get(
        "/excerpts/{chunk_id}",
        responses={
            **_REFUSALS,
            404: {"model": Problem, "description": "No chunk with this id that this caller may read."},
        },
    )
    async def excerpt(
        chunk_id: Annotated[str, Path(pattern=CHUNK_ID)], request: Request, who: Annotated[Identity, Depends(reader)]
    ) -> ExcerptOut:
        throttle(who)
        services: Services = request.app.state.services
        passage = await services.assistant.excerpt(who, chunk_id)
        if passage is None:
            # One answer for "not yours" and "not there": saying which would tell the caller that a document on the
            # subject exists above their clearance (ADR 0009).
            raise HTTPException(404, "no such excerpt")
        return ExcerptOut.model_validate(
            {
                "chunk_id": passage.chunk_id,
                "title": passage.title,
                "section": passage.heading,
                "text": passage.text,
                "classification": passage.classification,
                "department": passage.department,
            }
        )

    @app.get("/healthz")
    async def healthz(request: Request) -> JSONResponse:
        services: Services = request.app.state.services
        try:
            await services.pool.fetchval("select 1")
        except OSError, asyncpg.PostgresError:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        # One generic message out, the detail in the log under an id the caller can quote to support.
        reference = str(uuid.uuid4())
        log.error("unhandled", reference=reference, path=request.url.path, error_type=type(error).__name__)
        return JSONResponse({"detail": "the assistant is unavailable", "reference": reference}, status_code=503)

    app.include_router(protected)
    return app
