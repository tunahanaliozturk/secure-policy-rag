// What the page says about an outcome, a failure and a redaction. Plain sentences, kept in one file so that the
// wording is reviewed in one place and every view says the same thing about the same event.

import type { Failure } from '@/shared/api/http'
import type { Outcome } from '@/shared/api/policy'

export interface Wording {
  title: string
  detail: string
}

export const OUTCOME_WORDS: Record<Outcome, Wording> = {
  answered: { title: 'Answered', detail: 'The answer cites its sources and passed the citation and link checks.' },
  refused: {
    title: 'No answer',
    detail: 'The policies this person may read do not cover the question, so no answer was given.',
  },
  blocked: {
    title: 'Answer withheld',
    detail: 'An answer was written, but it failed the citation or link checks, so it is not shown.',
  },
  model_refused: { title: 'Model declined', detail: 'The answer model declined this question. Nothing was written.' },
  error: { title: 'Failed', detail: 'The assistant failed while answering. Nothing was written.' },
}

const plural = (count: number, one: string, many: string): string => `${count} ${count === 1 ? one : many}`

export function describeFailure(failure: Failure, who: string): Wording {
  switch (failure.kind) {
    case 'unauthorised':
      return {
        title: 'Sign-in expired',
        detail: `The sign-in for ${who} expired, and renewing it did not work. Sign in again.`,
      }
    case 'rate_limited':
      return {
        title: 'Too many requests',
        detail:
          failure.retryAfterSeconds === null
            ? `${who} has sent too many requests. Wait a minute, then try again.`
            : `${who} has sent too many requests. Wait ${plural(failure.retryAfterSeconds, 'second', 'seconds')}, then try again.`,
      }
    case 'unavailable':
      return {
        title: 'The assistant is unavailable',
        detail:
          failure.reference === null
            ? 'Nothing was answered, and the server gave no reference for the failure. Try again shortly.'
            : `Nothing was answered. If you report this, quote reference ${failure.reference}.`,
      }
    case 'not_found':
      return { title: 'Not found', detail: 'The server has nothing at this address for this person.' }
    case 'rejected':
      return {
        title: 'Request refused',
        detail: `The server refused the request with status ${failure.status}. A question must be 1 to 2,000 characters.`,
      }
    case 'network':
      return {
        title: 'No answer from the server',
        detail: 'The request did not get through. Check the connection, then try again.',
      }
    case 'contract':
      return {
        title: 'Unexpected response',
        detail: 'The server answered in a form this page does not understand. Reload the page before trying again.',
      }
    case 'page':
      return { title: 'This page failed', detail: 'The page hit an error of its own. Reload it and try again.' }
    case 'cancelled':
      return {
        title: 'Signed out',
        detail: 'The request was dropped because the person signed out before it finished.',
      }
  }
}

const KINDS: Record<string, [one: string, many: string]> = {
  IBAN: ['IBAN', 'IBANs'],
  CARD: ['card number', 'card numbers'],
  TCKN: ['Turkish national id', 'Turkish national ids'],
  BSN: ['Dutch citizen service number', 'Dutch citizen service numbers'],
  EMAIL: ['email address', 'email addresses'],
  PHONE: ['phone number', 'phone numbers'],
}

/** "1 IBAN and 2 email addresses", or null when nothing was removed. A kind this page has no name for keeps the
 *  server's own label, so a new recogniser on the server is still reported. */
export function describeRedactions(counts: Record<string, number>): string | null {
  const parts = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([kind, count]) => {
      const [one, many] = KINDS[kind] ?? [kind, kind]
      return plural(count, one, many)
    })
  if (parts.length === 0) return null
  return new Intl.ListFormat('en', { style: 'long', type: 'conjunction' }).format(parts)
}
