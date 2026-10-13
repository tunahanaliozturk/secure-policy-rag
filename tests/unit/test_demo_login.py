"""The demo login: a separate process that hands a short-lived token to six named demo people and to nobody else."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from secure_policy_rag import cli, identity
from secure_policy_rag.demo_login import build_demo_login
from secure_policy_rag.identity import DEMO_IDENTITIES

SECRET = b"d" * 32
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
TTL = timedelta(minutes=10)
ROOT = Path(__file__).parents[2]


@pytest.fixture
def http() -> httpx.AsyncClient:
    app = build_demo_login(SECRET, TTL, now=lambda: NOW)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://login")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(DEMO_IDENTITIES))
async def test_each_demo_person_gets_a_ten_minute_token_the_api_would_accept(
    http: httpx.AsyncClient, name: str
) -> None:
    response = await http.post("/token", json={"name": name})

    assert response.status_code == 200
    body = response.json()
    who = DEMO_IDENTITIES[name]
    assert set(body) == {"token", "subject", "departments", "clearance", "expires_at"}
    assert (body["subject"], body["departments"], body["clearance"]) == (
        name,
        sorted(who.departments),
        who.clearance.label,
    )
    assert datetime.fromisoformat(body["expires_at"]) == NOW + TTL
    assert identity.verify(body["token"], [SECRET], NOW + TTL - timedelta(seconds=1)) == who
    with pytest.raises(identity.InvalidToken):
        identity.verify(body["token"], [SECRET], NOW + TTL)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["mallory", "root", "alice2", "erin.admin"])
async def test_a_well_formed_name_that_is_not_one_of_the_six_is_a_404_and_gets_no_token(
    http: httpx.AsyncClient, name: str
) -> None:
    response = await http.post("/token", json={"name": name})

    assert response.status_code == 404
    assert response.json() == {"detail": "no such demo identity"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "Alice"},
        {"name": "alice bob"},
        {"name": "a" * 65},
        {"name": ["alice"]},
        {"name": "alice", "clearance": "restricted"},
        {"name": "frank", "departments": ["security"]},
    ],
)
async def test_a_malformed_request_is_a_422_so_nobody_can_send_their_own_clearance(
    http: httpx.AsyncClient, body: dict[str, object]
) -> None:
    response = await http.post("/token", json=body)

    assert response.status_code == 422
    assert "token" not in response.text


@pytest.mark.asyncio
async def test_identities_lists_the_six_people_and_nothing_secret(http: httpx.AsyncClient) -> None:
    response = await http.get("/identities")

    assert response.status_code == 200
    assert response.json() == {
        "identities": [
            {"subject": "alice", "departments": ["credit"], "clearance": "confidential"},
            {"subject": "bob", "departments": ["compliance"], "clearance": "restricted"},
            {"subject": "carol", "departments": ["hr"], "clearance": "confidential"},
            {"subject": "dave", "departments": ["markets"], "clearance": "internal"},
            {"subject": "erin", "departments": ["data", "security"], "clearance": "restricted"},
            {"subject": "frank", "departments": [], "clearance": "public"},
        ]
    }
    assert SECRET.decode() not in response.text


@pytest.mark.asyncio
async def test_the_login_has_a_health_probe_and_only_the_three_routes(http: httpx.AsyncClient) -> None:
    assert (await http.get("/healthz")).json() == {"status": "ok"}
    app = build_demo_login(SECRET, TTL)
    assert set(app.openapi()["paths"]) == {"/token", "/identities"}


def test_the_api_process_has_no_route_that_could_mint_a_token() -> None:
    document = cli.openapi_documents()["api.openapi.json"]

    assert set(document["paths"]) == {"/ask", "/excerpts/{chunk_id}", "/healthz"}
    assert "token" not in json.dumps(document["components"]["schemas"]).lower()


def test_the_committed_openapi_documents_are_what_the_code_serves() -> None:
    # The browser client's types are generated from these two files (web/src/shared/api). CI regenerates them and
    # fails on a diff; this is the same check without Node, so `pytest` alone catches a contract that moved.
    for name, document in cli.openapi_documents().items():
        committed = (ROOT / "web/src/shared/api" / name).read_text(encoding="utf-8")
        assert committed == cli.render_openapi(document), f"{name} is stale: run `uv run spr openapi`"


def test_spr_openapi_writes_both_documents_without_a_database_or_a_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for variable in ["SPR_TOKEN_SECRET", "SPR_DATABASE_URL", "SPR_ADMIN_DATABASE_URL"]:
        monkeypatch.delenv(variable, raising=False)

    assert cli.main(["openapi", "--output", str(tmp_path)]) == 0

    assert sorted(p.name for p in tmp_path.iterdir()) == ["api.openapi.json", "login.openapi.json"]
    api = json.loads((tmp_path / "api.openapi.json").read_text(encoding="utf-8"))
    assert api["info"]["version"] == json.loads((tmp_path / "login.openapi.json").read_text("utf-8"))["info"]["version"]
