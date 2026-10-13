"""A stand-in login for the demo stack: a short-lived token for one of six named demo people, and for nobody else.

A bank's identity provider issues the tokens the API verifies (ADR 0005). The browser demo needs something to play
that part, so this does. It is a process of its own on purpose (ADR 0010): the API only ever verifies, so no setting
and no bug in the API can turn it into a token mint. There are no passwords, which means anyone who can reach this
service can be any of the six. Do not run it anywhere a stranger can reach.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from importlib.metadata import version

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from secure_policy_rag import identity
from secure_policy_rag.identity import DEMO_IDENTITIES, ClearanceLabel, Department, Identity
from secure_policy_rag.telemetry import FRAMEWORK_TELEMETRY


class Who(BaseModel):
    # Nothing but a name: a caller who sends their own clearance or departments is refused, not ignored.
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9._-]+$")


class Person(BaseModel):
    subject: str
    departments: list[Department]
    clearance: ClearanceLabel


class People(BaseModel):
    identities: list[Person]


class Issued(Person):
    token: str
    expires_at: datetime


class Problem(BaseModel):
    detail: str


def _person(who: Identity) -> dict[str, object]:
    return {"subject": who.subject, "departments": sorted(who.departments), "clearance": who.clearance.label}


LOCAL_HOSTS = ("127.0.0.1", "localhost")


def build_demo_login(
    secret: bytes,
    ttl: timedelta,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    allowed_hosts: Sequence[str] = LOCAL_HOSTS,
) -> FastAPI:
    app = FastAPI(
        title="secure-policy-rag demo login",
        version=version("secure-policy-rag"),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        telemetry=FRAMEWORK_TELEMETRY,
    )
    # With no password, the name a request was addressed to is the only thing left to check. A page on another site
    # whose DNS name is re-pointed at 127.0.0.1 still sends its own name in Host, and is refused with a 400 here.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts), www_redirect=False)

    @app.post("/token", responses={404: {"model": Problem, "description": "Not one of the demo identities."}})
    async def token(who: Who) -> Issued:
        person = DEMO_IDENTITIES.get(who.name)
        if person is None:
            raise HTTPException(404, "no such demo identity")
        issued_at = now()
        signed = identity.issue(person, secret, issued_at, ttl)
        return Issued.model_validate({**_person(person), "token": signed, "expires_at": issued_at + ttl})

    @app.get("/identities")
    async def identities() -> People:
        return People.model_validate({"identities": [_person(who) for who in DEMO_IDENTITIES.values()]})

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
