# 10. The demo login is a separate process, and the API never signs a token

Status: Accepted, 2026-10-13

## Context

The browser console needs a token for whoever the visitor picks, and a browser cannot run `docker compose exec api spr
token dave`. Something reachable over HTTP has to hand tokens out. The API holds the signing secret already, so the
shortest path is one more route on it. That route would be a token mint with no password in front of it, living in
the one process whose job is to trust tokens, one configuration mistake away from being reachable in a deployment
that was never meant to have it.

## Decision

`spr demo-login` runs a second, small FastAPI app (`demo_login.py`) as its own process and its own compose service.
`POST /token {"name": "alice"}` returns a ten-minute token for one of the six identities in
`identity.DEMO_IDENTITIES`; `GET /identities` lists the six. The API process has no route that issues a token.

## Consequences

- No setting turns the API into a mint. `test_the_api_process_has_no_route_that_could_mint_a_token` reads the API's
  OpenAPI document and requires exactly `/ask`, `/excerpts/{chunk_id}` and `/healthz`, and an import-linter contract
  forbids `api`, `pipeline` and `store` from importing `demo_login`.
- The login gets the signing secret and nothing else. In `compose.yaml` it has no database address and no model key,
  and a second import contract keeps `asyncpg`, the store and the pipeline out of it.
- Only the six names work. Any other well-formed name is a 404 and a request with extra fields is a 422, so a caller
  cannot send their own clearance (`test_a_malformed_request_is_a_422_so_nobody_can_send_their_own_clearance`). Each
  token is checked against `identity.verify`, the function the API uses, and is refused one second after ten minutes
  (`test_each_demo_person_gets_a_ten_minute_token_the_api_would_accept`).
- There are no passwords. Anyone who can reach the login can be any of the six, restricted clearance included. That is
  the point of a demo and the reason this service must not be reachable by strangers; the sign-in page says so in one
  sentence. Compose binds it to 127.0.0.1.
- One more process to run, and the secret now lives in two containers. Rotating it means restarting both.
- Ten minutes is short enough that the console has to renew tokens. It does so once on a 401 without telling the
  person, and says so if that fails (ADR 11).

## Alternatives

- **A `POST /demo-token` route on the API behind a setting.** One process fewer. Lost because the guarantee would be
  a boolean someone can flip, and because every later reader of `api.py` would have to check that the route is off.
  Would win only if the stack could not afford a second container.
- **Keycloak in compose.** The real shape of the thing this stands in for. Lost for the reason in ADR 5: a large
  moving part in every test run, for a repository about what happens after authentication.
- **Mint the six tokens at build time and bake them into the page.** No login service at all. Lost because the tokens
  would be long-lived secrets in a static file and the page could not show what an expired token looks like.
