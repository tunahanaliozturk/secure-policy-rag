import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { answer, fakeServer, held, json, PEOPLE, RUNBOOK, subjectOf } from '@/test/server'

import { ApiError, failureIn } from './http'
import { people, signedInAs, tokenFor } from './login'
import { ask, askSettled, excerpt } from './policy'
import { forgetTokens, heldToken } from './tokens'

beforeEach(() => {
  vi.useFakeTimers({ now: new Date('2026-10-13T12:00:00Z') })
})

afterEach(() => {
  forgetTokens()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

/** The failure a rejected call carries, so a test can assert on it as a value. */
async function failed(call: Promise<unknown>): Promise<unknown> {
  try {
    await call
  } catch (error) {
    return failureIn(error)
  }
  throw new Error('the call succeeded')
}

describe('the demo login', () => {
  it('lists the six people', async () => {
    fakeServer()

    const staff = await people()

    expect(staff.map((person) => person.subject)).toEqual(['alice', 'bob', 'carol', 'dave', 'erin', 'frank'])
    expect(staff[4]).toEqual({ subject: 'erin', departments: ['data', 'security'], clearance: 'restricted' })
  })

  it('refuses a list that does not match the contract', async () => {
    fakeServer({ 'GET /login/identities': () => json({ identities: [{ subject: 'alice', clearance: 'root' }] }) })

    expect(await failed(people())).toEqual({ kind: 'contract' })
  })

  it('asks for a token once and reuses it while it is good', async () => {
    const server = fakeServer()

    expect([await tokenFor('dave'), await tokenFor('dave')]).toEqual(['token-dave-1', 'token-dave-1'])
    expect(server.to('POST /login/token')).toHaveLength(1)
    expect(server.to('POST /login/token')[0]?.body).toEqual({ name: 'dave' })
  })

  it('keeps a token per person', async () => {
    fakeServer()

    expect([await tokenFor('dave'), await tokenFor('erin')]).toEqual(['token-dave-1', 'token-erin-1'])
  })

  it('asks again shortly before the token expires, and when told the last one was refused', async () => {
    fakeServer()
    await tokenFor('dave')

    vi.advanceTimersByTime(600_000 - 20_000)
    expect(await tokenFor('dave')).toBe('token-dave-2')
    expect(await tokenFor('dave', true)).toBe('token-dave-3')
  })

  it('forgets every token on sign-out', async () => {
    fakeServer()
    await tokenFor('dave')

    forgetTokens()

    expect(await tokenFor('dave')).toBe('token-dave-2')
  })

  it('drops a token that arrives after sign-out, keeps nothing, and sends nothing with it', async () => {
    const issued = held()
    const server = fakeServer({
      'POST /login/token': () => issued.response,
      'POST /api/ask': () => json(answer(RUNBOOK)),
    })
    const asking = failed(ask('alice', 'anything'))

    forgetTokens()
    const expires = new Date(Date.now() + 600_000).toISOString()
    issued.release(json({ ...PEOPLE[0], token: 'token-alice-1', expires_at: expires }))

    expect(await asking).toEqual({ kind: 'cancelled' })
    expect(heldToken('alice')).toBeNull()
    expect(server.to('POST /api/ask')).toEqual([])
  })

  it('reports a name the login does not know as not found, and a token that is not one as a broken contract', async () => {
    const server = fakeServer()
    expect(await failed(tokenFor('mallory'))).toEqual({ kind: 'not_found' })

    server.on('POST /login/token', () => json({ subject: 'dave', departments: [], clearance: 'internal', token: '' }))
    expect(await failed(tokenFor('dave'))).toEqual({ kind: 'contract' })
  })
})

describe('a request made as a person', () => {
  it('carries that person token', async () => {
    const server = fakeServer({ 'POST /api/ask': () => json(answer(RUNBOOK)) })

    const result = await ask('erin', 'Which systems are the crown jewel systems?')

    expect(result.citations).toEqual([
      { chunk_id: 'SEC-004#2', title: 'Security Incident Response Runbook', section: '2. Crown jewel systems' },
    ])
    expect(server.to('POST /api/ask')[0]).toMatchObject({
      bearer: 'token-erin-1',
      body: { question: 'Which systems are the crown jewel systems?' },
    })
  })

  it('signs in again once, without saying so, when the token is refused', async () => {
    let refusals = 1
    const server = fakeServer({
      'POST /api/ask': () =>
        refusals-- > 0 ? json({ detail: 'invalid or missing token' }, 401) : json(answer(RUNBOOK)),
    })

    const result = await ask('erin', 'anything')

    expect(result.outcome).toBe('answered')
    expect(server.to('POST /api/ask').map((call) => call.bearer)).toEqual(['token-erin-1', 'token-erin-2'])
  })

  it('gives up after the second refusal and says the sign-in is the problem', async () => {
    const server = fakeServer({ 'POST /api/ask': () => json({ detail: 'invalid or missing token' }, 401) })

    expect(await failed(ask('erin', 'anything'))).toEqual({ kind: 'unauthorised' })
    expect(server.to('POST /api/ask')).toHaveLength(2)
    expect(server.to('POST /login/token')).toHaveLength(2)
  })

  it('does not repeat a call that failed for any other reason', async () => {
    const server = fakeServer({ 'POST /api/ask': () => json({ detail: 'too many requests' }, 429) })

    await failed(ask('erin', 'anything'))

    expect(server.to('POST /api/ask')).toHaveLength(1)
  })

  it('passes on an error that is not a failed request', async () => {
    fakeServer()

    await expect(signedInAs('erin', () => Promise.reject(new RangeError('a bug')))).rejects.toThrow(RangeError)
  })
})

describe('what a failed request is called', () => {
  it.each([
    [
      json({ detail: 'too many requests' }, 429, { 'Retry-After': '17' }),
      { kind: 'rate_limited', retryAfterSeconds: 17 },
    ],
    [json({ detail: 'too many requests' }, 429), { kind: 'rate_limited', retryAfterSeconds: null }],
    [
      json({ detail: 'the assistant is unavailable', reference: '7f3c0e52' }, 503),
      { kind: 'unavailable', reference: '7f3c0e52' },
    ],
    [new Response('<html>502 Bad Gateway</html>', { status: 502 }), { kind: 'unavailable', reference: null }],
    [json({ detail: [{ msg: 'String should have at most 2000 characters' }] }, 422), { kind: 'rejected', status: 422 }],
    [json({ detail: 'Not Found' }, 404), { kind: 'not_found' }],
    [json({ outcome: 'answered', text: 'renamed field' }), { kind: 'contract' }],
    [json({ ...answer(RUNBOOK), outcome: 'maybe' }), { kind: 'contract' }],
    [new Response('not json', { status: 200 }), { kind: 'contract' }],
  ])('%#', async (response, failure) => {
    fakeServer({ 'POST /api/ask': () => response })

    expect(await failed(ask('dave', 'anything'))).toEqual(failure)
  })

  it.each([401, 404, 422, 429, 503])(
    'reads the body of a %i to its end, so the request is not left open',
    async (status) => {
      // A refusal whose body nobody reads stays in flight in the browser: with no-store, Chromium never finishes it.
      const refusal = json({ detail: 'refused' }, status)
      fakeServer({ 'GET /api/excerpts/SEC-004%232': () => refusal })

      await failed(excerpt('dave', 'SEC-004#2'))

      expect(refusal.bodyUsed).toBe(true)
    },
  )

  it('says the network failed when no answer came at all', async () => {
    fakeServer({ 'POST /api/ask': () => Promise.reject(new TypeError('fetch failed')) })

    expect(await failed(ask('dave', 'anything'))).toEqual({ kind: 'network' })
  })

  it('calls anything that is not a failed request the page own fault', () => {
    expect(failureIn(new RangeError('a bug'))).toEqual({ kind: 'page' })
    expect(failureIn(new ApiError({ kind: 'network' }))).toEqual({ kind: 'network' })
  })
})

describe('opening an excerpt', () => {
  it('asks for the chunk by its id, escaped, as the reader', async () => {
    const server = fakeServer({ 'GET /api/excerpts/SEC-004%232': () => json(RUNBOOK) })

    expect(await excerpt('erin', 'SEC-004#2')).toEqual(RUNBOOK)
    expect(server.to('GET /api/excerpts/SEC-004%232')[0]?.bearer).toBe('token-erin-1')
  })

  it('is not found for a reader the server shows nothing to', async () => {
    fakeServer({
      'GET /api/excerpts/SEC-004%232': (call) =>
        subjectOf(call) === 'erin' ? json(RUNBOOK) : json({ detail: 'no such excerpt' }, 404),
    })

    expect(await failed(excerpt('dave', 'SEC-004#2'))).toEqual({ kind: 'not_found' })
  })

  it('refuses an excerpt with a classification the contract does not have', async () => {
    fakeServer({ 'GET /api/excerpts/SEC-004%232': () => json({ ...RUNBOOK, classification: 'secret' }) })

    expect(await failed(excerpt('erin', 'SEC-004#2'))).toEqual({ kind: 'contract' })
  })
})

describe('asking without throwing', () => {
  it('returns the answer, or the failure as a value', async () => {
    fakeServer({
      'POST /api/ask': (call) =>
        subjectOf(call) === 'erin' ? json(answer(RUNBOOK)) : json({ detail: 'x' }, 429, { 'Retry-After': '3' }),
    })

    expect(await askSettled('erin', 'q')).toEqual({ answer: answer(RUNBOOK) })
    expect(await askSettled('dave', 'q')).toEqual({ failure: { kind: 'rate_limited', retryAfterSeconds: 3 } })
  })

  it('still throws when the page itself is at fault', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new Error('x')) }))
    // A body that cannot be read is a contract failure, not a bug: it is returned.
    expect(await askSettled('erin', 'q')).toEqual({ failure: { kind: 'contract' } })
  })
})
