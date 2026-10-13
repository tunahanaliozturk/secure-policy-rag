"""The demo login: a separate process that hands a short-lived token to six named demo people and to nobody else."""

import json
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts

from secure_policy_rag import cli, identity
from secure_policy_rag.api import RateLimiter, Services, create_app
from secure_policy_rag.demo_login import build_demo_login
from secure_policy_rag.identity import DEMO_IDENTITIES

SECRET = b"d" * 32
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
TTL = timedelta(minutes=10)
ROOT = Path(__file__).parents[2]


@pytest.fixture
def http() -> httpx.AsyncClient:
    app = build_demo_login(SECRET, TTL, now=lambda: NOW)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8441")


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
    # Every route the app answers on, the ones left out of its OpenAPI document included.
    assert served_paths(build_demo_login(SECRET, TTL)) == {"/token", "/identities", "/healthz"}
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert (await http.get(path)).status_code == 404, path


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["evil.example:8440", "evil.example", "127.0.0.1.evil.example", "login"])
async def test_a_request_addressed_to_another_host_name_gets_no_token(http: httpx.AsyncClient, host: str) -> None:
    # The precondition for DNS rebinding: a page on evil.example whose name is re-pointed at 127.0.0.1 still sends
    # Host: evil.example. With no password in front of the mint, the name it was addressed by is the only check left.
    response = await http.post("/token", json={"name": "erin"}, headers={"Host": host})

    assert response.status_code == 400
    assert "token" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["127.0.0.1:8441", "localhost:8440", "127.0.0.1", "localhost", "127.0.0.1:8000"])
async def test_the_names_the_stack_uses_for_the_login_are_accepted(http: httpx.AsyncClient, host: str) -> None:
    assert (await http.post("/token", json={"name": "erin"}, headers={"Host": host})).status_code == 200
    assert (await http.get("/healthz", headers={"Host": host})).status_code == 200


@pytest.mark.asyncio
async def test_the_list_of_accepted_host_names_can_be_set() -> None:
    app = build_demo_login(SECRET, TTL, allowed_hosts=["login.bank.example"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://login.bank.example") as http:
        assert (await http.get("/identities")).status_code == 200
        assert (await http.get("/identities", headers={"Host": "127.0.0.1"})).status_code == 400


@pytest.mark.asyncio
async def test_a_trailing_slash_on_the_login_is_a_404_not_a_redirect(http: httpx.AsyncClient) -> None:
    response = await http.get("/identities/")
    assert (response.status_code, "location" in response.headers) == (404, False)


def served_paths(app: FastAPI) -> set[str]:
    # Routes of an included router are not in app.routes directly; this walks them as the app resolves them.
    return {context.path for context in iter_route_contexts(app.routes) if context.path is not None}


def never_started() -> AbstractAsyncContextManager[Services]:
    raise AssertionError("the app is only inspected, never started")


def test_the_api_process_has_no_route_that_could_mint_a_token() -> None:
    # The registered routes, not the OpenAPI paths: a route can be served and left out of the document.
    app = create_app(never_started, [SECRET], RateLimiter(per_minute=1))
    document = cli.openapi_documents()["api.openapi.json"]

    assert served_paths(app) == {"/ask", "/excerpts/{chunk_id}", "/healthz"}
    assert "token" not in json.dumps(document["components"]["schemas"]).lower()


@pytest.mark.asyncio
async def test_the_api_serves_no_interactive_documentation_or_schema_route() -> None:
    app = create_app(never_started, [SECRET], RateLimiter(per_minute=1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as http:
        for path in ["/docs", "/redoc", "/openapi.json"]:
            assert (await http.get(path)).status_code == 404, path


@pytest.mark.parametrize("command", [["serve"], ["demo-login"]])
def test_neither_server_writes_an_access_log_because_an_address_is_caller_chosen_text(
    command: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # uvicorn's access log prints the path and the query string of every request as they arrived. The application's
    # own log lines carry ids and outcomes instead (docs/operations.md).
    started: dict[str, object] = {}
    monkeypatch.setenv("SPR_TOKEN_SECRET", SECRET.decode())
    monkeypatch.setattr("uvicorn.run", lambda app, **options: started.update(options))
    monkeypatch.setattr("secure_policy_rag.telemetry.configure", lambda *args: None)

    assert cli.main(command) == 0

    assert started["access_log"] is False


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
