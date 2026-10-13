// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from '@testing-library/vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { forgetTokens } from '@/shared/api/tokens'
import { signOut } from '@/shared/session'
import { openApp, words } from '@/test/app'
import {
  ACCEPTABLE_USE,
  answer,
  CROWN_JEWELS,
  fakeServer,
  held,
  json,
  PEOPLE,
  policyRoutes,
  RUNBOOK,
  subjectOf,
} from '@/test/server'

afterEach(() => {
  cleanup()
  signOut()
  forgetTokens()
  vi.unstubAllGlobals()
})

const compared = `/compare?q=${encodeURIComponent(CROWN_JEWELS)}`
const status = (): string => screen.getAllByRole('status')[0]?.textContent ?? ''

/** The table as rows of cell text, once every cell has stopped checking. */
async function ledger(): Promise<string[][]> {
  const table = await screen.findByRole('table')
  await waitFor(() => expect(within(table).queryByText('Checking')).toBeNull())
  return within(table)
    .getAllByRole('row')
    .map((row) => [...row.querySelectorAll('th, td')].map(words))
}

describe('asking as everyone', () => {
  it('needs nobody signed in, and asks nothing until there is a question', async () => {
    const server = fakeServer(policyRoutes())
    await openApp('/compare')

    expect(screen.getByRole('heading', { level: 1, name: 'Ask as everyone' })).toBeTruthy()
    await waitFor(() => expect(status()).toBe(''))
    expect(screen.queryByRole('table')).toBeNull()
    expect(server.to('POST /api/ask')).toEqual([])
  })

  it('sends the question once as each of the six people, each with their own token', async () => {
    const server = fakeServer(policyRoutes())
    await openApp(compared)
    await ledger()

    const asks = server.to('POST /api/ask')
    expect(asks.map((call) => call.bearer).sort()).toEqual(PEOPLE.map((person) => `token-${person.subject}-1`).sort())
    expect(new Set(asks.map((call) => JSON.stringify(call.body)))).toEqual(
      new Set([JSON.stringify({ question: CROWN_JEWELS })]),
    )
  })

  it('shows who cited which source, and for every cited source who else may open it', async () => {
    fakeServer(policyRoutes())
    await openApp(compared)

    const [head, ...body] = await ledger()

    expect(head).toEqual([
      'Person',
      'SEC-001#4 Acceptable Use Policy 4. Monitoring public security',
      'SEC-004#2 Security Incident Response Runbook 2. Crown jewel systems restricted security',
      'What they were told',
    ])
    expect(body.map((row) => row.slice(0, 3))).toEqual([
      ['alice credit confidential', 'Cited', 'No access'],
      ['bob compliance restricted', 'Cited', 'No access'],
      ['carol hr confidential', 'Cited', 'No access'],
      ['dave markets internal', 'Cited', 'No access'],
      ['erin data, security restricted', 'Can read', 'Cited'],
      ['frank no department public', 'Cited', 'No access'],
    ])
    expect(body[3]?.[3]).toBe(`Answered ${ACCEPTABLE_USE.text} [SEC-001#4]`)
    expect(body[4]?.[3]).toBe(`Answered ${RUNBOOK.text} [SEC-004#2]`)
  })

  it('checks every cell by asking the server as that person, never by working it out', async () => {
    const server = fakeServer(policyRoutes())
    await openApp(compared)
    await ledger()

    const reads = server.calls.filter((call) => call.path.startsWith('/api/excerpts/'))
    expect(reads.map((call) => `${subjectOf(call)} ${decodeURIComponent(call.path.slice(14))}`).sort()).toEqual(
      PEOPLE.flatMap((person) => [`${person.subject} SEC-001#4`, `${person.subject} SEC-004#2`]).sort(),
    )
  })

  it('announces that it is asking, then how it came out', async () => {
    const reply = held()
    // Six requests wait on one release; each needs a body of its own to read.
    fakeServer({ ...policyRoutes(), 'POST /api/ask': () => reply.response.then((response) => response.clone()) })
    await openApp(compared)

    await waitFor(() => expect(status()).toBe('Asking as 6 people.'))
    expect(screen.getByRole('button', { name: 'Ask as all six' })).toHaveProperty('disabled', true)

    reply.release(json(answer(ACCEPTABLE_USE)))

    await waitFor(() => expect(status()).toBe('Asked as 6 people: 6 answered. 1 source cited.'))
  })

  it('counts each outcome in the announcement', async () => {
    fakeServer({
      ...policyRoutes(),
      'POST /api/ask': (call) =>
        subjectOf(call) === 'frank'
          ? json({ outcome: 'refused', answer: 'Not from your policies.', citations: [], question_redactions: {} })
          : json(answer(subjectOf(call) === 'erin' ? RUNBOOK : ACCEPTABLE_USE)),
    })
    await openApp(compared)

    const [, ...body] = await ledger()

    expect(status()).toBe('Asked as 6 people: 5 answered, 1 no answer. 2 different sources cited.')
    expect(body[5]?.slice(1)).toEqual(['Can read', 'No access', 'No answer Not from your policies.'])
  })

  it('keeps five answers on the page when the sixth request is rate limited', async () => {
    fakeServer({
      ...policyRoutes(),
      'POST /api/ask': (call) =>
        subjectOf(call) === 'dave'
          ? json({ detail: 'too many requests' }, 429, { 'Retry-After': '9' })
          : json(answer(subjectOf(call) === 'erin' ? RUNBOOK : ACCEPTABLE_USE)),
    })
    await openApp(compared)

    const [, ...body] = await ledger()

    expect(body[3]?.[3]).toBe('Too many requests dave has sent too many requests. Wait 9 seconds, then try again.')
    expect(body[4]?.[3]).toContain('Answered')
    expect(status()).toBe('Asked as 6 people: 5 answered, 1 request failed. 2 different sources cited.')
  })

  it('says a cell was not checked, and why, when its request fails for a reason other than access', async () => {
    fakeServer({
      ...policyRoutes(),
      'GET /api/excerpts/SEC-004%232': (call) => {
        if (subjectOf(call) === 'erin') return json(RUNBOOK)
        if (subjectOf(call) === 'bob') return json({ detail: 'unavailable', reference: 'r1' }, 503)
        return json({ detail: 'no such excerpt' }, 404)
      },
    })
    await openApp(compared)

    const [, ...body] = await ledger()

    expect(body[1]?.[2]).toBe('Not checked: The assistant is unavailable')
    expect(body[0]?.[2]).toBe('No access')
  })

  it('opens a source as the person whose mark was selected, and closes it back to that mark', async () => {
    const server = fakeServer(policyRoutes())
    const { router, user } = await openApp(compared)
    await ledger()

    await user.click(screen.getByRole('link', { name: 'Cited: open SEC-004#2 as erin' }))

    const source = await screen.findByRole('region', { name: 'SEC-004#2 opened as erin' })
    expect(await within(source).findByText(RUNBOOK.text)).toBeTruthy()
    expect(router.currentRoute.value.query).toEqual({ q: CROWN_JEWELS, source: 'SEC-004#2', reader: 'erin' })
    // The cell already asked for this excerpt as erin, so opening it sends nothing new.
    expect(server.to('GET /api/excerpts/SEC-004%232').filter((call) => subjectOf(call) === 'erin')).toHaveLength(1)

    await user.click(within(source).getByRole('button', { name: 'Close this source' }))

    await waitFor(() => expect(screen.queryByRole('region', { name: /opened as/ })).toBeNull())
    expect(document.activeElement).toBe(screen.getByRole('link', { name: 'Cited: open SEC-004#2 as erin' }))
  })

  it('offers no way to open a source for a person the server refused, and refuses an address that tries', async () => {
    fakeServer(policyRoutes())
    await openApp(`${compared}&source=SEC-004%232&reader=dave`)
    await ledger()

    expect(screen.queryByRole('link', { name: /open SEC-004#2 as dave/ })).toBeNull()
    const source = screen.getByRole('region', { name: 'SEC-004#2 opened as dave' })
    expect((await within(source).findByRole('alert')).textContent).toContain('dave cannot open SEC-004#2')
    expect(within(source).queryByText(RUNBOOK.text)).toBeNull()
  })

  it('asks a new question from the box and drops the opened source', async () => {
    const server = fakeServer(policyRoutes())
    const { router, user } = await openApp(`${compared}&source=SEC-004%232&reader=erin`)
    await ledger()

    await user.clear(screen.getByRole('textbox', { name: 'Question' }))
    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'How long must my password be?')
    await user.click(screen.getByRole('button', { name: 'Ask as all six' }))

    await waitFor(() => expect(server.to('POST /api/ask')).toHaveLength(12))
    expect(router.currentRoute.value.query).toEqual({ q: 'How long must my password be?' })
    expect(screen.queryByRole('region', { name: /opened as/ })).toBeNull()
  })

  it('says what failed when the six people cannot be loaded, and asks nothing', async () => {
    const server = fakeServer({ ...policyRoutes(), 'GET /login/identities': () => json({ detail: 'x' }, 503) })
    const { user } = await openApp(compared)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('The assistant is unavailable')
    expect(server.to('POST /api/ask')).toEqual([])

    server.on('GET /login/identities', () => json({ identities: PEOPLE }))
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))

    expect((await ledger()).length).toBe(7)
  })
})
