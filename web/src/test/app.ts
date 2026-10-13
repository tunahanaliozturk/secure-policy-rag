// Mounts the whole page at an address, with its real router and a query cache of its own, so a view is tested the
// way it runs: behind the guard, inside the shell, fed from the address bar.

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { render, screen, waitFor } from '@testing-library/vue'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { createMemoryHistory, type Router } from 'vue-router'

import App from '@/App.vue'
import { queryClientConfig } from '@/query'
import { createAppRouter } from '@/router'

export interface Mounted {
  router: Router
  user: UserEvent
}

export async function openApp(path: string): Promise<Mounted> {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  render(App, { global: { plugins: [router, [VueQueryPlugin, { queryClient: new QueryClient(queryClientConfig) }]] } })
  return { router, user: userEvent.setup() }
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
