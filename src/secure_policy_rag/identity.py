"""Who is asking, and the signed bearer token that says so.

A token is ``base64url(claims JSON) + "." + base64url(HMAC-SHA256(secret, first part))``. It stands in for the OIDC
token a bank's identity provider would issue (ADR 0005): the app never parses a token it did not verify first, compares
signatures in constant time, and refuses expired tokens. Several secrets can be valid at once, newest first, so a
secret can be rotated without a synchronised restart.
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

type Department = Literal["credit", "compliance", "data", "security", "hr", "markets"]
DEPARTMENTS: frozenset[str] = frozenset(get_args(Department.__value__))


class Clearance(IntEnum):
    """Ordered: a clearance sees every classification at or below it. The database uses the same numbers."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, label: str) -> Clearance:
        return cls[label.upper()]


@dataclass(frozen=True)
class Identity:
    subject: str
    departments: frozenset[str]
    clearance: Clearance


class _Claims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sub: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9._-]+$")
    departments: list[Department] = Field(max_length=len(DEPARTMENTS))
    clearance: Literal["public", "internal", "confidential", "restricted"]
    exp: int


MAX_TOKEN_LENGTH = 2048


class InvalidToken(Exception):
    """Deliberately carries no detail for the caller: a bad signature and an expired token look the same outside."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: bytes, payload: str) -> str:
    return _b64encode(hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest())


def issue(identity: Identity, secret: bytes, now: datetime, ttl: timedelta) -> str:
    claims = _Claims.model_validate(
        {
            "sub": identity.subject,
            "departments": sorted(identity.departments),
            "clearance": identity.clearance.label,
            "exp": int((now + ttl).timestamp()),
        }
    )
    payload = _b64encode(claims.model_dump_json().encode("utf-8"))
    return f"{payload}.{_sign(secret, payload)}"


def verify(token: str, secrets: Sequence[bytes], now: datetime) -> Identity:
    """The identity a token carries, or :class:`InvalidToken`. ``secrets`` is newest first; any of them may match."""
    payload, dot, signature = token.partition(".")
    if not dot or not payload or not signature or len(token) > MAX_TOKEN_LENGTH:
        raise InvalidToken
    # Every candidate is checked even after a match, so timing does not reveal which secret signed the token.
    matched = [hmac.compare_digest(_sign(secret, payload), signature) for secret in secrets]
    if not any(matched):
        raise InvalidToken
    try:
        claims = _Claims.model_validate(json.loads(_b64decode(payload)))
    except ValueError:  # bad base64, bad UTF-8, bad JSON and a pydantic ValidationError are all ValueErrors
        raise InvalidToken from None
    if claims.exp <= now.timestamp():
        raise InvalidToken
    return Identity(claims.sub, frozenset(claims.departments), Clearance.parse(claims.clearance))


def can_read(reader: Identity, classification: Clearance, department: str) -> bool:
    """The access rule in Python, as the evaluation's independent oracle. Enforcement is the row-level security
    policy in schema.sql, never this function; the evaluation fails if the two ever disagree."""
    if reader.clearance < classification:
        return False
    return classification <= Clearance.INTERNAL or department in reader.departments


DEMO_IDENTITIES: dict[str, Identity] = {
    identity.subject: identity
    for identity in [
        Identity("alice", frozenset({"credit"}), Clearance.CONFIDENTIAL),
        Identity("bob", frozenset({"compliance"}), Clearance.RESTRICTED),
        Identity("carol", frozenset({"hr"}), Clearance.CONFIDENTIAL),
        Identity("dave", frozenset({"markets"}), Clearance.INTERNAL),
        Identity("erin", frozenset({"security", "data"}), Clearance.RESTRICTED),
        Identity("frank", frozenset(), Clearance.PUBLIC),
    ]
}
"""Six people the README, the evaluation set and the tests share. Frank is a contractor: public policies only."""
