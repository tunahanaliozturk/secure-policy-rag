// Mounts the whole page at an address, with its real router and a query cache of its own, so a view is tested the
// way it runs: behind the guard, inside the shell, fed from the address bar.

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { render, screen, waitFor } from '@testing-library/vue'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { createMemoryHistory, type Router, type RouteRecordRaw } from 'vue-router'

import App from '@/App.vue'
import { queryClientConfig } from '@/query'
import { createAppRouter } from '@/router'

export interface Mounted {
  router: Router
  user: UserEvent
  queries: QueryClient
}

export interface Opening {
  /** Called instead of reloading the browser when a view's script is missing. */
  reload?: (path: string) => void
  /** Routes to add before the first navigation, for a test that needs one that fails. */
  routes?: RouteRecordRaw[]
}

/** Opens the page at `path` the way a link or a typed address does: it is the first navigation of the page load. */
export async function openApp(path: string, opening: Opening = {}): Promise<Mounted> {
  const router = createAppRouter(createMemoryHistory(), opening.reload ?? (() => undefined))
  for (const route of opening.routes ?? []) router.addRoute(route)
  const queries = new QueryClient(queryClientConfig)
  // Asked for before the navigation, as main.ts does: a router whose first navigation has already failed never
  // settles a readiness promise requested afterwards.
  const ready = router.isReady().catch(() => undefined)
  await router.push(path).catch(() => undefined)
  await ready
  render(App, { global: { plugins: [router, [VueQueryPlugin, { queryClient: queries }]] } })
  return { router, user: userEvent.setup(), queries }
}

/** Opens the page at `path` as `subject`, through the sign-in page, the way a person gets there. */
export async function openAppAs(subject: string, path: string): Promise<Mounted> {
  const mounted = await openApp(`/?next=${encodeURIComponent(path)}`)
  await mounted.user.click(await screen.findByRole('button', { name: `Sign in as ${subject}` }))
  await waitFor(() => {
    if (mounted.router.currentRoute.value.name === 'sign-in') throw new Error('still on the sign-in page')
  })
  await screen.findByRole('heading', { level: 1, name: /^Ask/ })
  return mounted
}

/** The text a person would read in `element`, one space between the pieces, whatever elements they sit in. */
export function words(element: Element | null | undefined): string {
  if (!element) return ''
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
  const pieces: string[] = []
  while (walker.nextNode()) pieces.push((walker.currentNode.textContent ?? '').replace(/\s+/g, ' ').trim())
  return pieces.filter((piece) => piece !== '').join(' ')
}
