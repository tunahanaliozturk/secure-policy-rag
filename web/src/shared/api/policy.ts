// The policy API (src/secure_policy_rag/api.py), proxied under /api: ask a question, open one cited excerpt. Both
// run as a named person, and the server decides from that person's token what exists for them.

import { z } from 'zod'

import type { components, paths } from './api.schema'
import type { Exact, Holds } from './contract'
import { ApiError, send, type Failure } from './http'
import { ClearanceSchema, DepartmentSchema, signedInAs } from './login'

type Wire = components['schemas']

export const OUTCOMES = ['answered', 'refused', 'blocked', 'model_refused', 'error'] as const
export type Outcome = (typeof OUTCOMES)[number]

const CitationSchema = z.object({ chunk_id: z.string().min(1), title: z.string(), section: z.string() })
export type Citation = z.output<typeof CitationSchema>

const AnswerSchema = z.object({
  outcome: z.enum(OUTCOMES),
  answer: z.string(),
  citations: z.array(CitationSchema),
  question_redactions: z.record(z.string(), z.number().int()),
})
export type Answer = z.output<typeof AnswerSchema>

const ExcerptSchema = z.object({
  chunk_id: z.string().min(1),
  title: z.string(),
  section: z.string(),
  text: z.string(),
  classification: ClearanceSchema,
  department: DepartmentSchema,
})
export type Excerpt = z.output<typeof ExcerptSchema>

export type _AnswerMatchesTheServer = Holds<Exact<Answer, Wire['AskResponse']>>
export type _ExcerptMatchesTheServer = Holds<Exact<Excerpt, Wire['ExcerptOut']>>

const ASK = '/ask' satisfies keyof paths
const EXCERPT = '/excerpts/{chunk_id}' satisfies keyof paths

const bearer = (token: string): Record<string, string> => ({ Authorization: `Bearer ${token}` })

export function ask(subject: string, question: string): Promise<Answer> {
  return signedInAs(subject, (token) =>
    send(
      `/api${ASK}`,
      {
        method: 'POST',
        headers: { ...bearer(token), 'Content-Type': 'application/json' },
        body: JSON.stringify({ question } satisfies Wire['AskRequest']),
      },
      AnswerSchema,
    ),
  )
}

/** One chunk as this person may read it. A chunk they may not read and a chunk that does not exist both fail with
 *  `not_found`: the server gives one answer for both, on purpose. */
export function excerpt(subject: string, chunkId: string, signal?: AbortSignal): Promise<Excerpt> {
  const path = EXCERPT.replace('{chunk_id}', encodeURIComponent(chunkId))
  return signedInAs(subject, (token) =>
    send(`/api${path}`, { headers: bearer(token), signal: signal ?? null }, ExcerptSchema),
  )
}

export type Asked = { answer: Answer; failure?: never } | { failure: Failure; answer?: never }

/** `ask`, with a request that failed returned as a value: one person's 429 must not hide five people's answers. */
export async function askSettled(subject: string, question: string): Promise<Asked> {
  try {
    return { answer: await ask(subject, question) }
  } catch (error) {
    if (error instanceof ApiError) return { failure: error.failure }
    throw error
  }
}
