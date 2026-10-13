import type { QueryClientConfig } from '@tanstack/vue-query'

/**
 * How server data is cached. Nothing is fetched again behind the person's back: every excerpt request is written to
 * the server's record of who opened what, so a refetch on window focus would log reads nobody made. A failed request
 * is not retried either, because a 404, a 429 and a 401 each mean something the page has to show.
 */
export const queryClientConfig: QueryClientConfig = {
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
  },
}
