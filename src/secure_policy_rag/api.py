"""HTTP: ``POST /ask`` behind a bearer token, and an unauthenticated ``GET /healthz`` for the container probe.

Every route on ``protected`` requires a valid token, so a route added later is authenticated unless someone moves it
out deliberately. The rate limit is keyed on the verified subject, never on anything the caller can choose freely.
"""

import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import asyncpg
import structlog
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from secure_policy_rag import identity
from secure_policy_rag.identity import Identity
from secure_policy_rag.pipeline import Assistant, Outcome

log = structlog.get_logger()


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

    app = FastAPI(title="secure-policy-rag", version="0.1.0", lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def reader(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Identity:
        try:
            if credentials is None:
                raise identity.InvalidToken
            return identity.verify(credentials.credentials, token_secrets, now())
        except identity.InvalidToken:
            raise HTTPException(401, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"}) from None

    protected = APIRouter(dependencies=[Depends(reader)])

    @protected.post("/ask")
    async def ask(body: AskRequest, request: Request, who: Annotated[Identity, Depends(reader)]) -> AskResponse:
        if (wait := limiter.retry_after(who.subject)) > 0:
            raise HTTPException(429, "too many requests", headers={"Retry-After": str(int(wait) + 1)})
        services: Services = request.app.state.services
        answer = await services.assistant.ask(who, body.question)
        return AskResponse(
            outcome=answer.outcome,
            answer=answer.text,
            citations=[CitationOut(chunk_id=c.chunk_id, title=c.title, section=c.section) for c in answer.citations],
            question_redactions=answer.redactions,
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
