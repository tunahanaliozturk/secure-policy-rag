# 5. HMAC-signed demo tokens in place of an identity provider

Status: Accepted, 2026-10-06

## Context

A bank would authenticate staff through its identity provider and read department and clearance from token claims or
an entitlement service. A portfolio repository cannot ship a bank's identity provider, and a Keycloak container would
add a large moving part to every test run without changing anything this repository is about.

## Decision

The API accepts a bearer token of the form `base64url(claims).base64url(HMAC-SHA256(secret, claims))`, with subject,
departments, clearance and expiry. Verification compares signatures with `hmac.compare_digest`, checks every configured
secret so timing does not reveal which one matched, validates claims against a fixed list of departments and levels,
and refuses an expired token. Two secrets can be active at once, so rotation is a configuration change. `spr token
<name>` mints a token for one of six demo identities.

## Consequences

- Callers cannot raise their own clearance: the claims are signed (tested).
- A department name cannot smuggle a comma into the database setting, because claims are checked against a fixed list
  before they get there (tested).
- There is no revocation. A token is valid until it expires, 60 minutes by default. Acceptable for a demo, not for
  production, where the identity provider's short-lived tokens and session revocation apply.
- Replacing this with OIDC means swapping `identity.verify` for a JWT library that checks signature, issuer, audience
  and expiry against the provider's keys. Nothing downstream changes, because everything else consumes `Identity`.

## Alternatives

- **Keycloak in compose.** Realistic, and the right choice for a system that has to be integrated somewhere. Lost on
  weight for a repository whose subject is what happens after authentication.
- **JWT with HS256.** Same security properties, more parsing surface, and the old temptation to accept `alg` from the
  token. Lost on simplicity.
