"""Walks the README quick start against a running ``docker compose up`` stack and fails loudly on any wrong step.

Standard library only. Mints its tokens inside the api container, exactly as the README does:

    uv run --no-project python tools/smoke.py
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:8400"


def token(subject: str) -> str:
    command = ["docker", "compose", "exec", "-T", "api", "spr", "token", subject]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603


def ask(question: str, bearer: str | None) -> tuple[int, Any]:
    request = urllib.request.Request(  # noqa: S310  # fixed local base URL
        f"{BASE}/ask", data=json.dumps({"question": question}).encode(), method="POST"
    )
    request.add_header("Content-Type", "application/json")
    if bearer:
        request.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def check(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL {message}")
        sys.exit(1)
    print(f"ok   {message}")


def main() -> None:
    with urllib.request.urlopen(f"{BASE}/healthz", timeout=10) as response:  # noqa: S310
        check(json.loads(response.read()) == {"status": "ok"}, "health check reports ok")

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


if __name__ == "__main__":
    main()
