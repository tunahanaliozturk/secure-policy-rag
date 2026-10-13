// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from '@testing-library/vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { components } from '@/shared/api/api.schema'
import { forgetTokens } from '@/shared/api/tokens'
import { signOut } from '@/shared/session'
import { openAppAs, words } from '@/test/app'
import { ACCEPTABLE_USE, answer, CROWN_JEWELS, fakeServer, held, json, policyRoutes, RUNBOOK } from '@/test/server'

type AskResponse = components['schemas']['AskResponse']

afterEach(() => {
  cleanup()
  signOut()
  forgetTokens()
  vi.unstubAllGlobals()
})

const asked = (question: string): string => `/ask?q=${encodeURIComponent(question)}`
const status = (): string => screen.getAllByRole('status')[0]?.textContent ?? ''

async function typeAndAsk(user: Awaited<ReturnType<typeof openAppAs>>['user'], question: string): Promise<void> {
  await user.type(screen.getByRole('textbox', { name: 'Question' }), question)
  await user.click(screen.getByRole('button', { name: 'Ask' }))
}

describe('asking a question', () => {
  it('shows who is asking, with their department and clearance', async () => {
    fakeServer(policyRoutes())
    await openAppAs('erin', '/ask')

    expect(words(screen.getByText('You are asking as').parentElement)).toBe(
      'You are asking as erin data, security restricted',
    )
  })

  it('announces the request while it is out, then the outcome', async () => {
    const reply = held()
    const server = fakeServer({ ...policyRoutes(), 'POST /api/ask': () => reply.response })
    const { router, user } = await openAppAs('dave', '/ask')

    await typeAndAsk(user, CROWN_JEWELS)

    await waitFor(() => expect(status()).toBe('Asking as dave.'))
    expect(screen.getByRole('button', { name: 'Ask' })).toHaveProperty('disabled', true)
    expect(router.currentRoute.value.query).toEqual({ q: CROWN_JEWELS })

    reply.release(json(answer(ACCEPTABLE_USE)))

    await waitFor(() => expect(status()).toBe('Answered. 1 source cited.'))
    expect(server.to('POST /api/ask')[0]).toMatchObject({ bearer: 'token-dave-1', body: { question: CROWN_JEWELS } })
  })

  it('shows the answer as text and each cited source as a link', async () => {
    fakeServer(policyRoutes())
    await openAppAs('erin', asked(CROWN_JEWELS))

    const result = await screen.findByRole('region', { name: 'Result' })
    expect(within(result).getByText('Answered')).toBeTruthy()
    expect(within(result).getByText(`${RUNBOOK.text} [SEC-004#2]`)).toBeTruthy()
    const sources = within(within(result).getByRole('list', { name: 'Sources cited' })).getAllByRole('link')
    expect(sources.map(words)).toEqual(['SEC-004#2 Security Incident Response Runbook, 2. Crown jewel systems'])
  })

  it('asks from the address alone, so a result can be reloaded or sent to someone', async () => {
    const server = fakeServer(policyRoutes())
    await openAppAs('dave', asked(CROWN_JEWELS))

    await screen.findByRole('region', { name: 'Result' })
    expect(screen.getByRole('textbox', { name: 'Question' })).toHaveProperty('value', CROWN_JEWELS)
    expect(server.to('POST /api/ask')).toHaveLength(1)
  })

  it('sends the same question again when asked to, as a new request', async () => {
    const server = fakeServer(policyRoutes())
    const { user } = await openAppAs('dave', asked(CROWN_JEWELS))
    await screen.findByRole('region', { name: 'Result' })

    await user.click(screen.getByRole('button', { name: 'Ask' }))

    await waitFor(() => expect(server.to('POST /api/ask')).toHaveLength(2))
  })

  it('asks an example question when its button is pressed', async () => {
    const server = fakeServer(policyRoutes())
    const { user } = await openAppAs('dave', '/ask')

    await user.click(screen.getByRole('button', { name: CROWN_JEWELS }))

    await screen.findByRole('region', { name: 'Result' })
    expect(server.to('POST /api/ask')[0]?.body).toEqual({ question: CROWN_JEWELS })
  })

  it('says what was removed from the question', async () => {
    fakeServer({ ...policyRoutes(), 'POST /api/ask': () => json(answer(ACCEPTABLE_USE, { IBAN: 1, EMAIL: 1 })) })
    await openAppAs('dave', asked('My IBAN is NL91 ABNA 0417 1643 00 and my email is me@example.com.'))

    const result = await screen.findByRole('region', { name: 'Result' })
    expect(words(within(result).getByText('Removed from the question').parentElement)).toBe(
      'Removed from the question before it was searched or sent to the model: 1 IBAN and 1 email address.',
    )
  })

  it('says nothing about redaction when nothing was removed', async () => {
    fakeServer(policyRoutes())
    await openAppAs('dave', asked(CROWN_JEWELS))

    await screen.findByRole('region', { name: 'Result' })
    expect(screen.queryByText('Removed from the question')).toBeNull()
  })

  it.each<[AskResponse['outcome'], string, string]>([
    ['refused', 'No answer', 'The policies this person may read do not cover the question, so no answer was given.'],
    [
      'blocked',
      'Answer withheld',
      'An answer was written, but it failed the citation or link checks, so it is not shown.',
    ],
    ['model_refused', 'Model declined', 'The answer model declined this question. Nothing was written.'],
    ['error', 'Failed', 'The assistant failed while answering. Nothing was written.'],
  ])('puts the outcome "%s" in words of its own, with no source list', async (outcome, title, detail) => {
    const reply: AskResponse = { outcome, answer: 'What the server said.', citations: [], question_redactions: {} }
    fakeServer({ ...policyRoutes(), 'POST /api/ask': () => json(reply) })
    await openAppAs('dave', asked(CROWN_JEWELS))

    const result = await screen.findByRole('region', { name: 'Result' })
    expect(within(result).getByText(title)).toBeTruthy()
    expect(within(result).getByText(detail)).toBeTruthy()
    expect(within(result).getByText('What the server said.')).toBeTruthy()
    expect(within(result).queryByRole('list', { name: 'Sources cited' })).toBeNull()
    expect(status()).toBe(`${title}. 0 sources cited.`)
  })
})

describe('when asking fails', () => {
  it('renews an expired sign-in once without telling the person', async () => {
    let refusals = 1
    const server = fakeServer({
      ...policyRoutes(),
      'POST /api/ask': () =>
        refusals-- > 0 ? json({ detail: 'invalid or missing token' }, 401) : json(answer(RUNBOOK)),
    })
    await openAppAs('erin', asked(CROWN_JEWELS))

    await screen.findByRole('region', { name: 'Result' })
    expect(screen.queryByRole('alert')).toBeNull()
    // One token to sign in, one for the question that was refused... and one fetched quietly after the 401.
    expect(server.to('POST /login/token')).toHaveLength(2)
    expect(server.to('POST /api/ask').map((call) => call.bearer)).toEqual(['token-erin-1', 'token-erin-2'])
  })

  it('says the sign-in expired when renewing it does not help, and links to sign in again', async () => {
    fakeServer({ ...policyRoutes(), 'POST /api/ask': () => json({ detail: 'invalid or missing token' }, 401) })
    const { router, user } = await openAppAs('erin', asked(CROWN_JEWELS))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Sign-in expired')
    expect(alert.textContent).toContain('The sign-in for erin expired, and renewing it did not work. Sign in again.')
    expect(screen.queryByRole('region', { name: 'Result' })).toBeNull()

    await user.click(within(alert).getByRole('link', { name: 'Sign in again' }))
    await screen.findByRole('heading', { level: 1, name: 'Sign in as a member of staff' })
    expect(router.currentRoute.value.query.next).toBe(asked(CROWN_JEWELS))
  })

  it('shows how long to wait after a 429', async () => {
    fakeServer({
      ...policyRoutes(),
      'POST /api/ask': () => json({ detail: 'too many requests' }, 429, { 'Retry-After': '17' }),
    })
    await openAppAs('dave', asked(CROWN_JEWELS))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Too many requests')
    expect(alert.textContent).toContain('dave has sent too many requests. Wait 17 seconds, then try again.')
    expect(status()).toBe('')
  })

  it('shows the reference the API returned with a 503, and asks again on request', async () => {
    const server = fakeServer({
      ...policyRoutes(),
      'POST /api/ask': () => json({ detail: 'the assistant is unavailable', reference: '7f3c0e52-1a2b' }, 503),
    })
    const { user } = await openAppAs('dave', asked(CROWN_JEWELS))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('The assistant is unavailable')
    expect(alert.textContent).toContain('If you report this, quote reference 7f3c0e52-1a2b.')

    server.on('POST /api/ask', () => json(answer(ACCEPTABLE_USE)))
    await user.click(within(alert).getByRole('button', { name: 'Ask again' }))

    await screen.findByRole('region', { name: 'Result' })
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says the request did not get through when the network fails', async () => {
    fakeServer({ ...policyRoutes(), 'POST /api/ask': () => Promise.reject(new TypeError('fetch failed')) })
    await openAppAs('dave', asked(CROWN_JEWELS))

    expect((await screen.findByRole('alert')).textContent).toContain(
      'The request did not get through. Check the connection, then try again.',
    )
  })

  it('refuses to show an answer that does not match the contract', async () => {
    fakeServer({ ...policyRoutes(), 'POST /api/ask': () => json({ outcome: 'answered', text: 'a renamed field' }) })
    await openAppAs('dave', asked(CROWN_JEWELS))

    expect((await screen.findByRole('alert')).textContent).toContain('Unexpected response')
    expect(screen.queryByText('a renamed field')).toBeNull()
  })
})

describe('opening a cited source', () => {
  it('opens the excerpt as the signed-in person, moves focus to it, and puts it in the address', async () => {
    const server = fakeServer(policyRoutes())
    const { router, user } = await openAppAs('erin', asked(CROWN_JEWELS))

    await user.click(await screen.findByRole('link', { name: /SEC-004#2/ }))

    const source = await screen.findByRole('region', { name: 'SEC-004#2 opened as erin' })
    expect(await within(source).findByText(RUNBOOK.text)).toBeTruthy()
    expect(within(source).getByText('Security Incident Response Runbook')).toBeTruthy()
    expect(words(within(source).getByText('Classification').parentElement)).toBe('Classification restricted')
    expect(words(within(source).getByText('Owning department').parentElement)).toBe('Owning department security')
    expect(document.activeElement).toBe(within(source).getByRole('heading', { level: 2 }))
    expect(router.currentRoute.value.query).toEqual({ q: CROWN_JEWELS, source: 'SEC-004#2' })
    expect(server.to('GET /api/excerpts/SEC-004%232')[0]?.bearer).toBe('token-erin-1')
    expect(screen.getByRole('link', { name: /SEC-004#2/ }).getAttribute('aria-current')).toBe('true')
  })

  it('closes the excerpt and puts focus back on the link that opened it', async () => {
    fakeServer(policyRoutes())
    const { router, user } = await openAppAs('erin', asked(CROWN_JEWELS))
    await user.click(await screen.findByRole('link', { name: /SEC-004#2/ }))
    await screen.findByText(RUNBOOK.text)

    await user.click(screen.getByRole('button', { name: 'Close this source' }))

    await waitFor(() => expect(screen.queryByRole('region', { name: /opened as/ })).toBeNull())
    expect(router.currentRoute.value.query).toEqual({ q: CROWN_JEWELS })
    expect(document.activeElement).toBe(screen.getByRole('link', { name: /SEC-004#2/ }))
  })

  it('says the person cannot open a source the server returns a 404 for, and shows none of it', async () => {
    fakeServer(policyRoutes())
    await openAppAs('dave', `${asked(CROWN_JEWELS)}&source=SEC-004%232`)

    const source = await screen.findByRole('region', { name: 'SEC-004#2 opened as dave' })
    const alert = await within(source).findByRole('alert')
    expect(alert.textContent).toContain('dave cannot open SEC-004#2')
    expect(alert.textContent).toContain('this page cannot tell which of the two this is')
    expect(screen.queryByText(RUNBOOK.text)).toBeNull()
    expect(screen.queryByText('Security Incident Response Runbook')).toBeNull()
  })

  it('ignores a source in the address that is not shaped like a chunk id, and sends nothing for it', async () => {
    const server = fakeServer(policyRoutes())
    await openAppAs('dave', `${asked(CROWN_JEWELS)}&source=..%2F..%2Fadmin`)

    await screen.findByRole('region', { name: 'Result' })
    expect(screen.queryByRole('region', { name: /opened as/ })).toBeNull()
    expect(server.calls.filter((call) => call.path.startsWith('/api/excerpts'))).toEqual([])
  })

  it('offers another try when the excerpt request fails for a reason other than access', async () => {
    const server = fakeServer({
      ...policyRoutes(),
      'GET /api/excerpts/SEC-001%234': () => json({ detail: 'too many requests' }, 429, { 'Retry-After': '5' }),
    })
    const { user } = await openAppAs('dave', `${asked(CROWN_JEWELS)}&source=SEC-001%234`)

    const source = await screen.findByRole('region', { name: 'SEC-001#4 opened as dave' })
    const alert = await within(source).findByRole('alert')
    expect(alert.textContent).toContain('Wait 5 seconds, then try again.')

    server.on('GET /api/excerpts/SEC-001%234', () => json(ACCEPTABLE_USE))
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))

    expect(await within(source).findByText(ACCEPTABLE_USE.text)).toBeTruthy()
  })
})
