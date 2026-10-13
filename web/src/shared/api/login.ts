// The demo stack's login (src/secure_policy_rag/demo_login.py), proxied under /login. It hands a ten-minute token to
// six named demo people. In a bank this is the identity provider; the API only checks what it issued.

import { z } from 'zod'

import type { Exact, Holds } from './contract'
import { ApiError, send } from './http'
import type { components, paths } from './login.schema'
import { heldToken, holdToken, tokenEpoch } from './tokens'

type Wire = components['schemas']

export const ClearanceSchema = z.enum(['public', 'internal', 'confidential', 'restricted'])
export const DepartmentSchema = z.enum(['credit', 'compliance', 'data', 'security', 'hr', 'markets'])
export type Clearance = z.output<typeof ClearanceSchema>

const PersonSchema = z.object({
  subject: z.string().min(1),
  departments: z.array(DepartmentSchema),
  clearance: ClearanceSchema,
})
export type Person = z.output<typeof PersonSchema>

const PeopleSchema = z.object({ identities: z.array(PersonSchema) })
const IssuedSchema = PersonSchema.extend({ token: z.string().min(1), expires_at: z.iso.datetime({ offset: true }) })

export type _PeopleMatchTheServer = Holds<Exact<z.output<typeof PeopleSchema>, Wire['People']>>
export type _IssuedMatchesTheServer = Holds<Exact<z.output<typeof IssuedSchema>, Wire['Issued']>>

const IDENTITIES = '/identities' satisfies keyof paths
const TOKEN = '/token' satisfies keyof paths

/** The six people the demo can sign in as. */
export async function people(signal?: AbortSignal): Promise<Person[]> {
  const body = await send(`/login${IDENTITIES}`, { signal: signal ?? null }, PeopleSchema)
  return body.identities
}

/** A token for this person: the one already held while it is good, otherwise a new one from the login. */
export async function tokenFor(subject: string, fresh = false): Promise<string> {
  const current = fresh ? null : heldToken(subject)
  if (current !== null) return current
  const epoch = tokenEpoch()
  const issued = await send(
    `/login${TOKEN}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: subject } satisfies Wire['Who']),
    },
    IssuedSchema,
  )
  // The person signed out while the login was answering. The token is not kept, and the request that wanted it is
  // not sent: signing out ends what was under way, not only what was already on the page.
  if (epoch !== tokenEpoch()) throw new ApiError({ kind: 'cancelled' })
  holdToken(subject, issued.token, Date.parse(issued.expires_at))
  return issued.token
}

/**
 * Runs `call` as this person. A 401 means the token expired or the secret was rotated, neither of which the person
 * can do anything about, so a new token is fetched and the call repeated once without telling them. A second 401 is
 * passed on: by then asking again will not help, and the page has to say so.
 */
export async function signedInAs<T>(subject: string, call: (token: string) => Promise<T>): Promise<T> {
  try {
    return await call(await tokenFor(subject))
  } catch (error) {
    if (!(error instanceof ApiError) || error.failure.kind !== 'unauthorised') throw error
    return call(await tokenFor(subject, true))
  }
}
