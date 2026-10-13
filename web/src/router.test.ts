// @vitest-environment jsdom
import { cleanup, screen, within } from '@testing-library/vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RouteRecordRaw } from 'vue-router'

import { forgetTokens } from '@/shared/api/tokens'
import { signOut } from '@/shared/session'
import { openApp } from '@/test/app'
import { fakeServer } from '@/test/server'

afterEach(() => {
  cleanup()
  signOut()
  forgetTokens()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

/** A route whose script does not arrive, as after a deploy that replaced the files this page was built with. */
const GONE: RouteRecordRaw = {
  path: '/gone',
  name: 'gone',
  component: () =>
    Promise.reject(new TypeError('Failed to fetch dynamically imported module: http://desk.test/assets/Gone-1a2b.js')),
}
const BROKEN: RouteRecordRaw = {
  path: '/broken',
  name: 'broken',
  component: () => Promise.reject(new RangeError('a bug')),
}

describe('a view whose script cannot be loaded', () => {
  it('reloads the page at the address the person was going to, once', async () => {
    fakeServer()
    const reload = vi.fn()
    const { router } = await openApp('/', { reload, routes: [GONE] })

    await router.push('/gone?q=kept').catch(() => undefined)

    expect(reload.mock.calls).toEqual([['/gone?q=kept']])
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says so, with a link to try again, when the reload did not help', async () => {
    fakeServer()
    const reload = vi.fn()
    const first = await openApp('/', { reload, routes: [GONE] })
    await first.router.push('/gone').catch(() => undefined)
    cleanup()

    // The page after that reload: a new router in the same tab, opened at the address that failed.
    await openApp('/gone', { reload, routes: [GONE] })

    expect(reload).toHaveBeenCalledTimes(1)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('This page could not be loaded')
    expect(within(alert).getByRole('link', { name: 'Load it again' }).getAttribute('href')).toBe('/gone')
  })

  it('forgets the earlier failure once a page loads, so the next one gets its reload', async () => {
    fakeServer()
    const reload = vi.fn()
    const { router } = await openApp('/', { reload, routes: [GONE] })
    await router.push('/gone').catch(() => undefined)
    expect(sessionStorage.length).toBe(1)

    await router.push('/compare')
    expect(sessionStorage.length).toBe(0)
    expect(screen.queryByRole('alert')).toBeNull()
    await router.push('/gone').catch(() => undefined)

    expect(reload).toHaveBeenCalledTimes(2)
  })

  it('does not reload for an error that is not a missing script, and says the page failed', async () => {
    fakeServer()
    const reload = vi.fn()
    const { router } = await openApp('/', { reload, routes: [BROKEN] })

    await router.push('/broken').catch(() => undefined)

    expect(reload).not.toHaveBeenCalled()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { level: 1, name: 'This page could not be loaded' })).toBeTruthy()
    // The page before it is not left on screen under the notice.
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('does not reload when the tab has no storage to remember that it already did', async () => {
    // Storage can be switched off in a browser. Without a place to note the reload, a second one cannot be ruled
    // out, so the page says it failed instead of risking a loop.
    fakeServer()
    const reload = vi.fn()
    const { router } = await openApp('/', { reload, routes: [GONE] })
    vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => {
      throw new DOMException('storage is disabled', 'SecurityError')
    })

    await router.push('/gone').catch(() => undefined)

    expect(reload).not.toHaveBeenCalled()
    expect((await screen.findByRole('alert')).textContent).toContain('This page could not be loaded')
    vi.restoreAllMocks()
  })

  it('keeps nothing in the tab storage after an ordinary visit', async () => {
    fakeServer()
    const { router } = await openApp('/')
    await router.push('/compare')

    expect(sessionStorage.length).toBe(0)
  })
})
