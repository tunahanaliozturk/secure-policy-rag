// A stand-in for the two servers, at the network layer: it replaces `fetch`, so everything above it runs as shipped,
// the token handling, the retry on 401, the schema parse. Nothing in the app's own modules is stubbed.

import { vi } from 'vitest'

import type { components as Api } from '@/shared/api/api.schema'
import type { components as Login } from '@/shared/api/login.schema'

export interface Call {
  method: string
  path: string
  bearer: string | null
  body: unknown
}

export type Handler = (call: Call) => Response | Promise<Response>

export const json = (body: unknown, status = 200, headers: Record<string, string> = {}): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })

export const PEOPLE: Login['schemas']['Person'][] = [
  { subject: 'alice', departments: ['credit'], clearance: 'confidential' },
  { subject: 'bob', departments: ['compliance'], clearance: 'restricted' },
  { subject: 'carol', departments: ['hr'], clearance: 'confidential' },
  { subject: 'dave', departments: ['markets'], clearance: 'internal' },
  { subject: 'erin', departments: ['data', 'security'], clearance: 'restricted' },
  { subject: 'frank', departments: [], clearance: 'public' },
]

export const RUNBOOK: Api['schemas']['ExcerptOut'] = {
  chunk_id: 'SEC-004#2',
  title: 'Security Incident Response Runbook',
  section: '2. Crown jewel systems',
  text: 'The crown jewel systems are the payments hub and the core banking ledger.',
  classification: 'restricted',
  department: 'security',
}

export const ACCEPTABLE_USE: Api['schemas']['ExcerptOut'] = {
  chunk_id: 'SEC-001#4',
  title: 'Acceptable Use Policy',
  section: '4. Monitoring',
  text: 'The Bank monitors the use of its systems to protect customers and the Bank.',
  classification: 'public',
  department: 'security',
}

export function answer(
  excerpt: Api['schemas']['ExcerptOut'],
  redactions: Record<string, number> = {},
): Api['schemas']['AskResponse'] {
  return {
    outcome: 'answered',
    answer: `${excerpt.text} [${excerpt.chunk_id}]`,
    citations: [{ chunk_id: excerpt.chunk_id, title: excerpt.title, section: excerpt.section }],
    question_redactions: redactions,
  }
}

/** Who a bearer token issued by {@link fakeServer} belongs to: tokens look like `token-dave-1`. */
export const subjectOf = (call: Call): string => call.bearer?.split('-')[1] ?? ''

export const CROWN_JEWELS = 'Which systems are the crown jewel systems?'

/**
 * The policy API as it behaves for the crown jewel question on the real corpus: erin, in security with restricted
 * clearance, is answered from the runbook; everyone else is answered from the public acceptable use policy and gets a
 * 404 for the runbook.
 */
export function policyRoutes(): Record<string, Handler> {
  return {
    'POST /api/ask': (call) => json(answer(subjectOf(call) === 'erin' ? RUNBOOK : ACCEPTABLE_USE)),
    'GET /api/excerpts/SEC-004%232': (call) =>
      subjectOf(call) === 'erin' ? json(RUNBOOK) : json({ detail: 'no such excerpt' }, 404),
    'GET /api/excerpts/SEC-001%234': () => json(ACCEPTABLE_USE),
  }
}

/** A response a test releases when it chooses, to look at the page while the request is still out. */
export function held(): { response: Promise<Response>; release: (response: Response) => void } {
  let release: (response: Response) => void = () => undefined
  const response = new Promise<Response>((resolve) => {
    release = resolve
  })
  return { response, release: (value) => release(value) }
}

export interface FakeServer {
  calls: Call[]
  /** Calls to one route, for example `calls('POST /api/ask')`. */
  to: (route: string) => Call[]
  /** Replaces or adds a route after the server was created. */
  on: (route: string, handler: Handler) => void
}

/**
 * Serves the demo login as the real one does, with tokens numbered per person, plus whatever `routes` adds or
 * replaces. A route is `'METHOD /path'`. A request to anything else is answered 501, which no test expects.
 */
export function fakeServer(routes: Record<string, Handler> = {}): FakeServer {
  const issued = new Map<string, number>()
  const table = new Map<string, Handler>(
    Object.entries({
      'GET /login/identities': () => json({ identities: PEOPLE }),
      'POST /login/token': (call: Call) => {
        const name = typeof call.body === 'object' && call.body !== null && 'name' in call.body ? call.body.name : ''
        const person = PEOPLE.find((candidate) => candidate.subject === name)
        if (person === undefined) return json({ detail: 'no such demo identity' }, 404)
        const count = (issued.get(person.subject) ?? 0) + 1
        issued.set(person.subject, count)
        const expires = new Date(Date.now() + 600_000).toISOString()
        return json({ ...person, token: `token-${person.subject}-${count}`, expires_at: expires })
      },
      ...routes,
    }),
  )
  const calls: Call[] = []

  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = new Request(new URL(input instanceof Request ? input.url : input, 'http://desk.test'), init)
    const text = await request.text()
    const body: unknown = text === '' ? null : JSON.parse(text)
    const call: Call = {
      method: request.method,
      path: new URL(request.url).pathname,
      bearer: request.headers.get('Authorization')?.replace(/^Bearer /, '') ?? null,
      body,
    }
    calls.push(call)
    const handler = table.get(`${call.method} ${call.path}`)
    return handler === undefined ? json({ detail: 'the test set up no such route' }, 501) : handler(call)
  })

  return {
    calls,
    to: (route) => calls.filter((call) => `${call.method} ${call.path}` === route),
    on: (route, handler) => table.set(route, handler),
  }
}
