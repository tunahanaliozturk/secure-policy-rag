// The one place a response becomes a value. Every body is parsed by a schema here, and every way a request can fail
// is named, so a view shows what happened instead of a generic error.

import { z } from 'zod'

import type { components } from './api.schema'
import type { Exact, Holds } from './contract'

// Zod speeds up object parsing by compiling a parser with `new Function`, and finds out whether it may by trying.
// Under this page's content security policy the attempt is blocked and reported as a violation on every load, even
// though Zod then carries on without it. Every schema is parsed through this module, so the switch is thrown here,
// before any of them runs. The journeys fail on any reported violation (e2e/console.spec.ts).
z.config({ jitless: true })

export type Failure =
  /** 401 twice in a row: the token was refused, a new one was fetched, and that was refused too. */
  | { kind: 'unauthorised' }
  /** 429. `retryAfterSeconds` is the server's Retry-After header, or null when it sent none. */
  | { kind: 'rate_limited'; retryAfterSeconds: number | null }
  /** 5xx. `reference` is the id the API logs the failure under, or null when a proxy answered instead of the API. */
  | { kind: 'unavailable'; reference: string | null }
  | { kind: 'not_found' }
  /** Any other refusal, such as a 422 for a question that is too long. */
  | { kind: 'rejected'; status: number }
  /** The request never got an answer. */
  | { kind: 'network' }
  /** The answer did not have the shape the OpenAPI document promises. */
  | { kind: 'contract' }
  /** Not a request at all: this page's own code threw. */
  | { kind: 'page' }
  /** Dropped because the person signed out while it was under way. */
  | { kind: 'cancelled' }

export class ApiError extends Error {
  constructor(readonly failure: Failure) {
    super(`request failed: ${failure.kind}`)
    this.name = 'ApiError'
  }
}

const UnavailableSchema = z.object({ detail: z.string(), reference: z.string() })
export type _UnavailableMatchesTheServer = Holds<
  Exact<z.output<typeof UnavailableSchema>, components['schemas']['Unavailable']>
>

async function failureOf(response: Response): Promise<Failure> {
  // The body is read to its end whatever the status, though only a 5xx has anything this page uses. A body nobody
  // reads keeps the request in flight in the browser, and these answers are sent no-store, so nothing else ends it.
  const body: unknown = await response.json().catch(() => null)
  if (response.status === 401) return { kind: 'unauthorised' }
  if (response.status === 404) return { kind: 'not_found' }
  if (response.status === 429) {
    const seconds = Number.parseInt(response.headers.get('Retry-After') ?? '', 10)
    return { kind: 'rate_limited', retryAfterSeconds: Number.isNaN(seconds) ? null : seconds }
  }
  if (response.status >= 500) {
    const unavailable = UnavailableSchema.safeParse(body)
    return { kind: 'unavailable', reference: unavailable.success ? unavailable.data.reference : null }
  }
  return { kind: 'rejected', status: response.status }
}

/** Sends one request and returns its body as `schema` describes it, or throws an {@link ApiError}. */
export async function send<S extends z.ZodType>(url: string, init: RequestInit, schema: S): Promise<z.output<S>> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    throw new ApiError({ kind: 'network' })
  }
  if (!response.ok) throw new ApiError(await failureOf(response))
  const body = schema.safeParse(await response.json().catch(() => undefined))
  if (!body.success) throw new ApiError({ kind: 'contract' })
  return body.data
}

/** What went wrong, for a caller that caught something. Anything that is not an {@link ApiError} is this page's own
 *  fault, and is reported as such instead of being swallowed. */
export function failureIn(error: unknown): Failure {
  return error instanceof ApiError ? error.failure : { kind: 'page' }
}
