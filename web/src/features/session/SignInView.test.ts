// @vitest-environment jsdom
import { cleanup, screen, within } from '@testing-library/vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { afterSignIn, createAppRouter } from '@/router'
import { forgetTokens } from '@/shared/api/tokens'
import { signOut } from '@/shared/session'
import { openApp, openAppAs, words } from '@/test/app'
import { fakeServer, held, json, PEOPLE, policyRoutes } from '@/test/server'

afterEach(() => {
  cleanup()
  signOut()
  forgetTokens()
  vi.unstubAllGlobals()
})

describe('signing in', () => {
  it('says there are no passwords and lists the six people with their departments and clearance', async () => {
    fakeServer()
    await openApp('/')

    expect(screen.getByRole('heading', { level: 1, name: 'Sign in as a member of staff' })).toBeTruthy()
    expect(
      screen.getByText(
        'This is a demonstration with no passwords: anyone who can open this page can sign in as any of the six.',
      ),
    ).toBeTruthy()

    await screen.findByRole('button', { name: 'Sign in as alice' })
    const staff = within(screen.getByRole('list', { name: 'Staff you can sign in as' })).getAllByRole('listitem')
    expect(staff.map(words)).toEqual([
      'alice credit confidential Sign in as alice',
      'bob compliance restricted Sign in as bob',
      'carol hr confidential Sign in as carol',
      'dave markets internal Sign in as dave',
      'erin data, security restricted Sign in as erin',
      'frank no department public Sign in as frank',
    ])
    expect(screen.getByText('Nobody is signed in')).toBeTruthy()
  })

  it('announces that the list is loading', async () => {
    const identities = held()
    fakeServer({ 'GET /login/identities': () => identities.response })
    await openApp('/')

    expect(screen.getByRole('status').textContent).toBe('Loading the six people.')

    identities.release(json({ identities: PEOPLE }))
    await screen.findByRole('button', { name: 'Sign in as alice' })
    expect(screen.getByRole('status').textContent).toBe('')
  })

  it('signs a person in with a token of their own and opens the question box', async () => {
    const server = fakeServer()
    const { router, user } = await openApp('/')

    await user.click(await screen.findByRole('button', { name: 'Sign in as dave' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Ask the policy library' })).toBeTruthy()
    expect(router.currentRoute.value.fullPath).toBe('/ask')
    expect(words(screen.getByText('Signed in as', { exact: false }))).toBe('Signed in as dave')
    expect(server.to('POST /login/token').map((call) => call.body)).toEqual([{ name: 'dave' }])
  })

  it('says what failed and offers another try when the list cannot be loaded', async () => {
    const server = fakeServer({ 'GET /login/identities': () => Promise.reject(new TypeError('fetch failed')) })
    const { user } = await openApp('/')

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('No answer from the server')
    expect(screen.queryByRole('button', { name: 'Sign in as alice' })).toBeNull()

    server.on('GET /login/identities', () => json({ identities: PEOPLE }))
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('button', { name: 'Sign in as alice' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('stays on the page and shows the reference when the login cannot issue a token', async () => {
    fakeServer({ 'POST /login/token': () => json({ detail: 'the assistant is unavailable', reference: 'ab12' }, 503) })
    const { router, user } = await openApp('/')

    await user.click(await screen.findByRole('button', { name: 'Sign in as dave' }))

    expect((await screen.findByRole('alert')).textContent).toContain('quote reference ab12')
    expect(router.currentRoute.value.name).toBe('sign-in')
    expect(screen.getByText('Nobody is signed in')).toBeTruthy()
  })

  it('sends someone who opens a question with nobody signed in to sign in, then back to that question', async () => {
    fakeServer(policyRoutes())
    const { router, user } = await openApp('/ask?q=How%20long%20must%20my%20password%20be%3F')

    expect(router.currentRoute.value.name).toBe('sign-in')
    expect(router.currentRoute.value.query.next).toBe('/ask?q=How%20long%20must%20my%20password%20be%3F')
    await user.click(await screen.findByRole('button', { name: 'Sign in as dave' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Ask the policy library' })).toBeTruthy()
    expect(router.currentRoute.value.query).toEqual({ q: 'How long must my password be?' })
  })

  it('signs out by forgetting the person and the token', async () => {
    const server = fakeServer(policyRoutes())
    const { router, user } = await openAppAs('dave', '/ask')

    await user.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(await screen.findByText('Nobody is signed in')).toBeTruthy()
    expect(router.currentRoute.value.name).toBe('sign-in')
    await user.click(await screen.findByRole('button', { name: 'Sign in as dave' }))
    await screen.findByRole('heading', { level: 1, name: 'Ask the policy library' })
    expect(server.to('POST /login/token')).toHaveLength(2)
  })

  it('lets the signed-in person be changed and returns to the page they were on', async () => {
    fakeServer(policyRoutes())
    const { router, user } = await openAppAs('dave', '/ask?q=anything')

    await user.click(screen.getByRole('link', { name: 'Change person' }))
    await user.click(await screen.findByRole('button', { name: 'Sign in as erin' }))

    await screen.findByRole('heading', { level: 1, name: 'Ask the policy library' })
    expect(words(screen.getByText('Signed in as', { exact: false }))).toBe('Signed in as erin')
    expect(router.currentRoute.value.fullPath).toBe('/ask?q=anything')
  })
})

describe('where sign-in leads', () => {
  const router = createAppRouter()

  it('follows next only to a page of this app', () => {
    expect(afterSignIn(router, '/compare?q=x')).toBe('/compare?q=x')
    expect(afterSignIn(router, '/ask?q=x&source=SEC-004%232')).toBe('/ask?q=x&source=SEC-004%232')
    expect(afterSignIn(router, null)).toBe('/ask')
    expect(afterSignIn(router, '/')).toBe('/ask')
    expect(afterSignIn(router, '//evil.example/ask')).toBe('/ask')
    expect(afterSignIn(router, 'https://evil.example/ask')).toBe('/ask')
    expect(afterSignIn(router, '/nowhere')).toBe('/ask')
  })

  it('sends an address that is no page of this app to sign-in, and names each page in the title', async () => {
    fakeServer()
    const { router } = await openApp('/admin/users')

    expect(router.currentRoute.value.name).toBe('sign-in')
    expect(document.title).toBe('Sign in | Policy desk')
  })
})
