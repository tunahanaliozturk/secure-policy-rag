"""Walks the README quick start against a running ``docker compose up`` stack and fails loudly on any wrong step.

Standard library only. The first part mints its tokens inside the api container, exactly as the README does; the
second goes through the browser console's one origin, as the page does, with tokens from the demo login; the third
checks what the stack is configured with and what it wrote to its logs:

    uv run --no-project python tools/smoke.py
"""

import http.client
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:8400"
LOGIN = "http://127.0.0.1:8441"
WEB = "http://127.0.0.1:8440"
CSP = "default-src 'self'"
# Shaped like personal data in a question, and unlike anything the stack would write by itself.
SENTINEL = "NL91SMOKE0417164300"


def compose(*arguments: str) -> str:
    command = ["docker", "compose", *arguments]
    done = subprocess.run(command, check=True, capture_output=True, encoding="utf-8", errors="replace")  # noqa: S603
    return done.stdout + done.stderr


def token(subject: str) -> str:
    return compose("exec", "-T", "api", "spr", "token", subject).strip()


def call(
    url: str, bearer: str | None = None, body: object = None, headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    """GET, or POST when there is a body. Returns status, raw body and headers, for refusals as for answers. Status 0
    means the server closed the connection without answering."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method="GET" if body is None else "POST")  # noqa: S310
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if bearer:
        request.add_header("Authorization", f"Bearer {bearer}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # fixed local base URLs
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)
    except http.client.HTTPException, urllib.error.URLError, ConnectionError:
        return 0, b"", {}


def ask(question: str, bearer: str | None) -> tuple[int, Any]:
    status, raw, _ = call(f"{BASE}/ask", bearer, {"question": question})
    return status, json.loads(raw or b"null")


def check(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL {message}")
        sys.exit(1)
    print(f"ok   {message}")


def api() -> None:
    status, raw, _ = call(f"{BASE}/healthz")
    check(json.loads(raw) == {"status": "ok"}, "health check reports ok")

    status, _ = ask("How long must my password be?", None)
    check(status == 401, f"no token is refused (got {status})")

    dave, erin = token("dave"), token("erin")
    status, body = ask("How long must my password be?", dave)
    check(status == 200 and body["outcome"] == "answered", f"dave gets an answer (got {status} {body})")
    check(any(c["chunk_id"].startswith("SEC-002") for c in body["citations"]), "and it cites the password standard")

    crown = "Which systems are the crown jewel systems?"
    status, body = ask(crown, erin)
    check(any(c["chunk_id"].startswith("SEC-004") for c in body["citations"]), "erin's answer cites the runbook")
    status, body = ask(crown, dave)
    check(status == 200, f"dave may ask the same question (got {status})")
    check(not any(c["chunk_id"].startswith("SEC-004") for c in body["citations"]), "but never sees the runbook")
    check("CC-SEC-004" not in body["answer"], "and its control code does not appear")

    status, body = ask("My IBAN is NL91 ABNA 0417 1643 00. May I work from home?", dave)
    check(body["question_redactions"] == {"IBAN": 1}, f"the IBAN in a question is redacted (got {body})")

    for path in ("/docs", "/openapi.json", "/excerpts/SEC-004%232/"):
        status, _, headers = call(f"{BASE}{path}")
        check(status == 404 and "Location" not in headers, f"the API serves nothing at {path} (got {status})")


def console() -> None:
    status, raw, headers = call(f"{WEB}/")
    check(status == 200 and b'<div id="app">' in raw, f"the console page is served (got {status})")
    check(headers.get("Content-Security-Policy", "").startswith(CSP), "with a content security policy")
    script = re.search(rb'src="(/assets/[^"]+\.js)"', raw)
    check(script is not None, "and names its entry script")

    status, raw, headers = call(f"{WEB}/login/identities")
    people = [p["subject"] for p in json.loads(raw)["identities"]]
    check(people == ["alice", "bob", "carol", "dave", "erin", "frank"], f"the demo login lists six people ({people})")
    check(headers.get("Content-Security-Policy", "").startswith(CSP), "and proxied answers carry the policy too")

    status, _, _ = call(f"{WEB}/login/token", body={"name": "mallory"})
    check(status == 404, f"the demo login has no token for anyone else (got {status})")
    status, _, _ = call(f"{WEB}/login/token", body={"name": "frank", "clearance": "restricted"})
    check(status == 422, f"and refuses a caller who sends their own clearance (got {status})")

    tokens = {}
    for name in ("dave", "erin"):
        status, raw, headers = call(f"{WEB}/login/token", body={"name": name})
        check(status == 200, f"the demo login issues a token for {name} (got {status})")
        check(
            headers.get("Cache-Control") == "no-store",
            f"which the browser may not cache ({headers.get('Cache-Control')})",
        )
        tokens[name] = json.loads(raw)["token"]

    runbook, nowhere = f"{WEB}/api/excerpts/SEC-004%232", f"{WEB}/api/excerpts/SEC-999%232"
    status, raw, headers = call(runbook, tokens["erin"])
    check(status == 200 and json.loads(raw)["classification"] == "restricted", "erin opens the restricted runbook")
    check(
        headers.get("Cache-Control") == "no-store", f"which may not be cached either ({headers.get('Cache-Control')})"
    )
    hidden = call(runbook, tokens["dave"])
    absent = call(nowhere, tokens["dave"])
    check(hidden[0] == 404, f"dave gets a 404 for it (got {hidden[0]})")
    check(hidden[:2] == absent[:2], "which is the same answer as for a chunk that does not exist")

    status, raw, _ = call(f"{WEB}/api/excerpts/HR-007%233", tokens["dave"])
    text = json.loads(raw)["text"]
    check("travel-bank-portal" not in text and "[link removed]" in text, "a poisoned source's link is withheld")

    # Assets are named after their content and kept for a year; a miss must not be kept at all.
    status, _, headers = call(f"{WEB}{script.group(1).decode()}" if script else WEB)
    check(
        "immutable" in headers.get("Cache-Control", ""), f"a built asset may be cached ({headers.get('Cache-Control')})"
    )
    status, _, headers = call(f"{WEB}/assets/nope.js")
    check((status, headers.get("Cache-Control")) == (404, "no-store"), f"a missing one may not ({status}, {headers})")


def other_host_names() -> None:
    """A page on another site whose name is re-pointed at 127.0.0.1 sends that name in Host. With no password in front
    of the login, the name is what stands between such a page and a token."""
    evil = {"Host": "evil.example:8440"}
    status, raw, _ = call(f"{WEB}/login/token", body={"name": "erin"}, headers=evil)
    check(status == 0 and raw == b"", f"nginx drops a request addressed to another host name (got {status})")
    status, raw, _ = call(f"{WEB}/", headers=evil)
    check(status == 0, f"whatever it asks for (got {status})")
    status, raw, _ = call(f"{LOGIN}/token", body={"name": "erin"}, headers={"Host": "evil.example:8441"})
    check(status == 400 and b"token" not in raw, f"and the login refuses one that reaches it directly (got {status})")
    status, _, _ = call(f"{WEB.replace('127.0.0.1', 'localhost')}/login/identities")
    check(status == 200, f"while localhost is a name the console answers to (got {status})")


def configuration() -> None:
    services = json.loads(compose("config", "--format", "json"))["services"]
    for name in ("api", "login", "web"):
        given = services[name].get("environment") or {}
        for variable in ("SPR_ADMIN_DATABASE_URL", "SPR_APP_DB_PASSWORD"):
            check(variable not in given, f"the {name} service is not given {variable}")
    check("SPR_ADMIN_DATABASE_URL" in services["setup"]["environment"], "only setup, which migrates and ingests, is")
    check("SPR_DATABASE_URL" not in (services["login"].get("environment") or {}), "the login has no database address")


def logs() -> None:
    """The question is in the console's address (/ask?q=...), so anything that logs an address in full, or the
    Referer that carries it, would log the question. Nothing may."""
    question = urllib.parse.quote(f"My IBAN is {SENTINEL}. May I work from home?")
    referer = {"Referer": f"{WEB}/ask?q={question}"}
    asked = [f"{WEB}/ask", f"{WEB}/compare", f"{WEB}/assets/nope.js", f"{WEB}/api/healthz", f"{WEB}/login/identities"]
    for url in [*asked, f"{BASE}/healthz", f"{LOGIN}/identities"]:
        call(f"{url}?q={question}", headers=referer)
    written = compose("logs", "--no-color", "--since", "10m", "web", "api", "login")
    check("/compare" in written, "the web log records which page was asked for")
    check(SENTINEL not in written, "and no log of web, api or login holds the question or the Referer carrying it")


def main() -> None:
    api()
    console()
    other_host_names()
    configuration()
    logs()


if __name__ == "__main__":
    main()
