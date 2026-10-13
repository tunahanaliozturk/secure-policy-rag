"""Walks the README quick start against a running ``docker compose up`` stack and fails loudly on any wrong step.

Standard library only. The first half mints its tokens inside the api container, exactly as the README does; the
second half goes through the browser console's one origin, as the page does, with tokens from the demo login:

    uv run --no-project python tools/smoke.py
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:8400"
WEB = "http://127.0.0.1:8440"
CSP = "default-src 'self'"


def token(subject: str) -> str:
    command = ["docker", "compose", "exec", "-T", "api", "spr", "token", subject]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603


def call(url: str, bearer: str | None = None, body: object = None) -> tuple[int, bytes, dict[str, str]]:
    """GET, or POST when there is a body. Returns status, raw body and headers, for refusals as for answers."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method="GET" if body is None else "POST")  # noqa: S310
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if bearer:
        request.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # fixed local base URLs
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


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


def console() -> None:
    status, raw, headers = call(f"{WEB}/")
    check(status == 200 and b'<div id="app">' in raw, f"the console page is served (got {status})")
    check(headers.get("Content-Security-Policy", "").startswith(CSP), "with a content security policy")

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
        status, raw, _ = call(f"{WEB}/login/token", body={"name": name})
        check(status == 200, f"the demo login issues a token for {name} (got {status})")
        tokens[name] = json.loads(raw)["token"]

    runbook, nowhere = f"{WEB}/api/excerpts/SEC-004%232", f"{WEB}/api/excerpts/SEC-999%232"
    status, raw, _ = call(runbook, tokens["erin"])
    check(status == 200 and json.loads(raw)["classification"] == "restricted", "erin opens the restricted runbook")
    hidden = call(runbook, tokens["dave"])
    absent = call(nowhere, tokens["dave"])
    check(hidden[0] == 404, f"dave gets a 404 for it (got {hidden[0]})")
    check(hidden[:2] == absent[:2], "which is the same answer as for a chunk that does not exist")


def main() -> None:
    api()
    console()


if __name__ == "__main__":
    main()
