# 11. The browser console: a generated contract, parsed responses, state by lifetime, one origin

Status: Accepted, 2026-10-13

## Context

The repository's claim is that two people asking one question get different sources and that the database decided
that. Until now the only way to see it was two `curl` commands. A page that shows it has to be honest in the same way
the API is: it must not work out access for itself, must not trust a response it has not checked, and must not hold a
token where a script can find it later. It also has to stay small. It is a Vue 3 single-page app in `web/`, built to
the house standard for front ends; this record covers the four decisions that are not obvious from the code.

## Decision

We generate the client's types from the servers' OpenAPI documents and fail the build when they drift, parse every
response at run time as well, keep each piece of state where its lifetime puts it, and serve the page, the API and the
demo login from one origin.

**Contract.** `uv run spr openapi` writes both OpenAPI documents to `web/src/shared/api/` without a database or a
secret. `npm run gen:api` turns them into TypeScript types with `openapi-typescript`. All four files are committed.
Each response also has a Zod schema that is tied to the generated type in both directions (`contract.ts`), so a field
that is renamed, added or dropped on the server is a compile error at the schema. At run time `http.ts` parses every
body with that schema; there is no `as` at a network boundary.

**State.** Server data lives in the TanStack Query cache: asking is a mutation, an excerpt and the list of people are
queries. The question and the opened source live in the address, so a result can be reloaded, sent to someone, and
left with the back button. The signed-in person is one module-level ref (`shared/session.ts`), because the router
guard and the header both read it and there is nothing else to it. There is no Pinia.

**Tokens.** A token is held in a module-scope `Map` (`tokens.ts`) and nowhere else. On a 401 the client fetches a new
one and repeats the request once without telling the person; a second 401 is shown as an expired sign-in.

**Origin.** nginx serves the built page and proxies `/api/` to the API and `/login/` to the demo login. Every
response carries `Content-Security-Policy: default-src 'self'` with no inline script or style allowed.

## Consequences

- Drift fails three gates. With `AskResponse.answer` renamed to `text` on the server: the unit test
  `test_the_committed_openapi_documents_are_what_the_code_serves` failed with "api.openapi.json is stale"; after
  regenerating, `git diff --exit-code -- web/src/shared/api` exited 1; and `npm run type-check` exited 2 with
  `src/shared/api/policy.ts(37,45): error TS2344: Type 'false' does not satisfy the constraint 'true'`. CI runs the
  second and third as the `contract` and `web-static` jobs.
- A response that breaks the contract anyway is refused at the fetch site and shown as "Unexpected response", never
  rendered (`AskView.test.ts`, "refuses to show an answer that does not match the contract").
- The comparison view decides nothing about access. Each cell asks `GET /excerpts/{id}` with that person's token and
  shows the answer; `CompareView.test.ts` checks that all twelve requests are made for six people and two sources.
  The cost: one comparison sends 6 questions and one excerpt request per person for every source anyone cited, each
  recorded in `excerpt_log`, and the browser console logs a 404 for every "No access" cell. Those 404s are the
  server's answer, not a fault. With the scripted model each person cites one source, so that is at most 36 excerpt
  requests, and the demo stack raises the per-person rate limit from 20 to 60 a minute to leave room for it. A real
  model can cite up to five sources per person (`SPR_TOP_K`), which makes up to 30 columns and 30 excerpt requests
  per person in one comparison: more than the code's default of 20 a minute allows, and half of the demo stack's 60,
  so a second comparison within the minute runs into it. A cell the limit refused reads "Not checked: Too many
  requests". The table has no cap on its columns.
- A question in an address is shown, not sent, when that address is how the page was opened. One press of "Ask as
  all six" is six questions, six model calls with a real model behind it, and six audit rows; a link someone was sent
  must not be able to spend that by being opened. Inside the page, choosing a question sends it as before
  (`CompareView.test.ts`, "does not send a question that arrived with the link"; the comparison journey checks that
  no request leaves before the press). `/ask?q=` needs no such rule: nobody is signed in on a fresh page, so it
  leads to the sign-in page first.
- Signing out ends what is under way, not only what is on the page. Tokens are tied to a count of sign-outs: one
  that was asked for before a sign-out and arrives after it is thrown away, and the request that wanted it is not
  sent (`CompareView.test.ts`, "stops when the person signs out"). In-flight queries are cancelled and the cache is
  cleared. A request that had already left with a token cannot be recalled; its answer is dropped.
- Answers from the API and the login are sent `Cache-Control: no-store`, because the browser's HTTP cache outlives a
  sign-out. Chromium then never finishes a request whose body nobody reads, so the client reads every refusal to
  its end.
- A view is a script of its own. If it cannot be loaded, as after a deploy that replaced the files, the router
  reloads once to the address the person wanted, and if that does not help the shell says the page could not be
  loaded (journey "a view whose script is gone"). The one thing kept in `sessionStorage` is a marker that the reload
  happened, removed by the next page that loads; it holds no address and no question.
- A reload signs the person out, because the token and the session are memory only. The page sends them to sign in
  and then back to the address they had. The journey "a person signs in, asks" asserts that `localStorage`,
  `sessionStorage` and `document.cookie` are empty afterwards.
- Under this content security policy Zod's attempt to compile parsers with `new Function` is blocked and reported as
  a violation on every load. Lighthouse found it; `z.config({ jitless: true })` removes it, and every journey now
  fails on any violation the browser reports. Parsing is slower without the compiled path, which does not matter for
  responses of a few hundred bytes.
- The page is mounted only after the first route has loaded. Mounted earlier, the footer was painted under an empty
  page and then moved: a layout shift of 0.114 at a phone viewport, measured, and 0 after the change.
- The answer text is model output. It is rendered as text, never as HTML and never linkified, as
  `docs/threat-model.md` asks of any client (ESLint `vue/no-v-html` is an error).
- `openapi-typescript` 7.13 declares TypeScript 5 as its peer; the repository uses TypeScript 6.0, so `package.json`
  overrides that peer. The generator ran correctly on both documents. If a later version of either breaks the pairing,
  `npm run gen:api` fails in the `contract` job.
- One more image to build, scan and keep patched, and an nginx that resolves `api` and `login` once at start-up: after
  either container is recreated, the web container has to be restarted (docs/operations.md).

## Alternatives

- **Hand-written TypeScript interfaces.** No generator and no committed generated files. Lost because nothing would
  fail when the server changed. Would win for a client of a third-party API with no machine-readable contract.
- **Generated types only, no run-time parsing.** Less code and no schema library to ship. Lost because a type is a claim
  about a response, and a proxy error page or a stale server breaks the claim silently, three components deep.
- **Pinia for the session and the results.** Familiar. Lost because the session is one value and the results are
  server data, which a store would have to invalidate by hand.
- **Token in `sessionStorage` to survive a reload.** Friendlier. Lost because any script that ever runs on the page
  could read it, and a ten-minute demo token is cheap to fetch again. Would lose to an `HttpOnly` cookie in a real
  deployment, which the bank's identity provider would set, not this page.
- **The API on its own origin with CORS.** No proxy. Lost because it needs a CORS policy on the API and a wider
  `connect-src`, both of which are new ways to be wrong, for nothing the demo needs.
- **Work out access in the page from clearance and department.** No extra requests and no 404s in the console. Lost
  because the table would then show what the page believes, and the point is to show what the database does.
