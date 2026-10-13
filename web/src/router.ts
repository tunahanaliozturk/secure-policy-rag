// Nothing imported here may pull in the schema library or the API client: this file is part of the first chunk, and
// every view is loaded when its route is.

import {
  createRouter,
  createWebHistory,
  type RouteLocationNormalized,
  type Router,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'

import { signedIn } from '@/shared/session'

/** The same shapes the server accepts (api.py, identity.py). The address bar is input like any other. */
const CHUNK_ID = /^[A-Z]{2,5}-\d{3}#\d{1,3}$/
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
      return { question: questionOf(route), open }
    },
  },
  { path: '/:rest(.*)*', redirect: { name: 'sign-in' } },
]

export function createAppRouter(history: RouterHistory = createWebHistory()): Router {
  const router = createRouter({ history, routes })

  router.afterEach((to, from) => {
    document.title = typeof to.meta.title === 'string' ? `${to.meta.title} | Policy desk` : 'Policy desk'
    if (to.path === from.path) return
    // A new page: move focus to its heading, or a screen reader stays where the old page was.
    requestAnimationFrame(() => document.querySelector<HTMLElement>('h1')?.focus())
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
