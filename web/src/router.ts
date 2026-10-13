// Nothing imported here may pull in the schema library or the API client: this file is part of the first chunk, and
// every view is loaded when its route is.

import {
  createRouter,
  type RouteLocationNormalized,
  type Router,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'
import { shallowRef } from 'vue'

import { signedIn } from '@/shared/session'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    /** True when this navigation was the first of the page load. Set by the router, never by a route. */
    byLink?: boolean
  }
}

/** The same shapes the server accepts (api.py, identity.py). The address bar is input like any other. */
const CHUNK_ID = /^[A-Z]{2,5}-[0-9]{3}#[0-9]{1,3}$/
const SUBJECT = /^[a-z0-9._-]{1,64}$/
const MAX_QUESTION = 2000

function one(route: RouteLocationNormalized, key: string): string | null {
  const value = route.query[key]
  return typeof value === 'string' ? value : null
}

function matching(route: RouteLocationNormalized, key: string, pattern: RegExp): string | null {
  const value = one(route, key)
  return value !== null && pattern.test(value) ? value : null
}

function questionOf(route: RouteLocationNormalized): string {
  return (one(route, 'q') ?? '').trim().slice(0, MAX_QUESTION)
}

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'sign-in',
    component: () => import('@/features/session/SignInView.vue'),
    meta: { title: 'Sign in' },
    props: (route) => ({ next: one(route, 'next') }),
  },
  {
    path: '/ask',
    name: 'ask',
    component: () => import('@/features/ask/AskView.vue'),
    meta: { title: 'Ask' },
    // A question is asked as somebody. With nobody signed in, pick a person first and come back to this address.
    beforeEnter: (to) => (signedIn.value === null ? { name: 'sign-in', query: { next: to.fullPath } } : true),
    props: (route) => ({ question: questionOf(route), source: matching(route, 'source', CHUNK_ID) }),
  },
  {
    path: '/compare',
    name: 'compare',
    component: () => import('@/features/compare/CompareView.vue'),
    meta: { title: 'Ask as everyone' },
    props: (route) => {
      const source = matching(route, 'source', CHUNK_ID)
      const reader = matching(route, 'reader', SUBJECT)
      // An excerpt is opened as somebody: one without the other opens nothing.
      const open = source !== null && reader !== null ? { source, reader } : null
      return { question: questionOf(route), open, byLink: route.meta.byLink === true }
    },
  },
  { path: '/:rest(.*)*', redirect: { name: 'sign-in' } },
]

/** The address of a page that could not be loaded, for the shell to say so. Null while all is well. */
export const loadFailure = shallowRef<string | null>(null)

/** Set in the tab's session storage while a reload for a missing script is under way, and removed by the next page
 *  that loads. It holds no address and no question, only the fact. */
const RELOADED = 'policy-desk:reloaded-for-a-missing-script'
/** How Chromium, Firefox, WebKit and Vite's preloader each word a lazy import that did not arrive. */
const MISSING_SCRIPT = /dynamically imported module|importing a module script failed|unable to preload/i

function tabStorage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

/**
 * `reload` leaves this page for a fresh copy of it at `path`. It is handed in by whoever builds the router (main.ts
 * passes the browser's own), so that what the router decides can be tested without a browser to reload.
 */
export function createAppRouter(history: RouterHistory, reload: (path: string) => void): Router {
  const router = createRouter({ history, routes })

  // The first navigation of a page load is somebody following a link or typing an address, not somebody pressing a
  // button in this app. A view that would spend something on arrival can tell the two apart (CompareView).
  let arrived = false
  router.beforeResolve((to) => {
    to.meta.byLink = !arrived
  })

  router.afterEach((to, from, failure) => {
    if (failure !== undefined) return
    arrived = true
    loadFailure.value = null
    tabStorage()?.removeItem(RELOADED)
    document.title = typeof to.meta.title === 'string' ? `${to.meta.title} | Policy desk` : 'Policy desk'
    if (to.path === from.path) return
    // A new page: move focus to its heading, or a screen reader stays where the old page was.
    requestAnimationFrame(() => document.querySelector<HTMLElement>('h1')?.focus())
  })

  // A view is a script of its own, fetched when its route is opened. After a deploy the script this page knows by
  // name is gone, and without this the click would do nothing at all. One reload to the address the person wanted
  // fetches the new page. If that does not help, or the error is something else, the shell says the page failed.
  router.onError((error, to) => {
    arrived = true
    const tab = tabStorage()
    const missingScript = error instanceof Error && MISSING_SCRIPT.test(error.message)
    if (missingScript && tab !== null && tab.getItem(RELOADED) === null) {
      tab.setItem(RELOADED, '1')
      reload(to.fullPath)
      return
    }
    loadFailure.value = to.fullPath
  })

  return router
}

/** Where to go after signing in: `next` if it names a page of this app, otherwise the question box. */
export function afterSignIn(router: Router, next: string | null): string {
  if (next !== null && next.startsWith('/') && !next.startsWith('//')) {
    const target = router.resolve(next)
    if (target.name === 'ask' || target.name === 'compare') return target.fullPath
  }
  return '/ask'
}
