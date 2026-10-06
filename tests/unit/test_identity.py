import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from secure_policy_rag import identity
from secure_policy_rag.identity import DEMO_IDENTITIES, Clearance, Identity, can_read

SECRET = b"k" * 32
OLD_SECRET = b"o" * 32
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
ALICE = DEMO_IDENTITIES["alice"]


def mint(who: Identity = ALICE, secret: bytes = SECRET, ttl: timedelta = timedelta(minutes=10)) -> str:
    return identity.issue(who, secret, NOW, ttl)


def test_a_token_round_trips_to_the_same_identity() -> None:
    assert identity.verify(mint(), [SECRET], NOW) == ALICE


def test_a_token_signed_with_the_previous_secret_still_works_during_a_rotation() -> None:
    assert identity.verify(mint(secret=OLD_SECRET), [SECRET, OLD_SECRET], NOW) == ALICE


def test_a_token_from_a_retired_secret_is_refused() -> None:
    with pytest.raises(identity.InvalidToken):
        identity.verify(mint(secret=OLD_SECRET), [SECRET], NOW)


def test_an_expired_token_is_refused() -> None:
    token = mint(ttl=timedelta(minutes=10))
    assert identity.verify(token, [SECRET], NOW + timedelta(minutes=9))
    with pytest.raises(identity.InvalidToken):
        identity.verify(token, [SECRET], NOW + timedelta(minutes=10))


def test_raising_your_own_clearance_in_the_payload_breaks_the_signature() -> None:
    payload, signature = mint().split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["clearance"] = "restricted"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(identity.InvalidToken):
        identity.verify(f"{forged}.{signature}", [SECRET], NOW)


@pytest.mark.parametrize("token", ["", ".", "abc", "abc.", ".abc", "a.b.c", "x" * 3000, "é.abc", "abc.é"])
def test_malformed_tokens_are_refused_without_detail(token: str) -> None:
    with pytest.raises(identity.InvalidToken) as raised:
        identity.verify(token, [SECRET], NOW)
    assert str(raised.value) == ""


def test_a_correctly_signed_token_with_an_unknown_department_is_refused() -> None:
    # Someone holding the secret still cannot put a comma-separated list into the database setting.
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "x", "departments": ["hr,credit"], "clearance": "public", "exp": 2**40}).encode()
    ).decode()
    signed = f"{payload}.{identity._sign(SECRET, payload)}"
    with pytest.raises(identity.InvalidToken):
        identity.verify(signed, [SECRET], NOW)


@pytest.mark.parametrize(
    ("classification", "department", "readable_by"),
    [
        (Clearance.PUBLIC, "hr", {"alice", "bob", "carol", "dave", "erin", "frank"}),
        (Clearance.INTERNAL, "hr", {"alice", "bob", "carol", "dave", "erin"}),
        (Clearance.CONFIDENTIAL, "hr", {"carol"}),
        (Clearance.CONFIDENTIAL, "markets", set()),  # dave is markets but only internal
        (Clearance.RESTRICTED, "security", {"erin"}),
        (Clearance.RESTRICTED, "credit", set()),  # alice is credit but only confidential
    ],
)
def test_the_access_rule(classification: Clearance, department: str, readable_by: set[str]) -> None:
    assert {s for s, who in DEMO_IDENTITIES.items() if can_read(who, classification, department)} == readable_by
