import { describe, expect, it } from 'vitest'

import type { Failure } from '@/shared/api/http'
import { OUTCOMES } from '@/shared/api/policy'

import { describeFailure, describeRedactions, OUTCOME_WORDS } from './words'

describe('describeFailure', () => {
  it('gives the wait the server asked for', () => {
    expect(describeFailure({ kind: 'rate_limited', retryAfterSeconds: 17 }, 'dave').detail).toBe(
      'dave has sent too many requests. Wait 17 seconds, then try again.',
    )
    expect(describeFailure({ kind: 'rate_limited', retryAfterSeconds: 1 }, 'dave').detail).toContain('Wait 1 second,')
    expect(describeFailure({ kind: 'rate_limited', retryAfterSeconds: null }, 'dave').detail).toContain('Wait a minute')
  })

  it('quotes the reference the server logged the failure under, and says so when there is none', () => {
    expect(describeFailure({ kind: 'unavailable', reference: '7f3c0e52' }, 'dave').detail).toBe(
      'Nothing was answered. If you report this, quote reference 7f3c0e52.',
    )
    expect(describeFailure({ kind: 'unavailable', reference: null }, 'dave').detail).toContain('no reference')
  })

  it('names the person whose sign-in ran out', () => {
    expect(describeFailure({ kind: 'unauthorised' }, 'erin').detail).toBe(
      'The sign-in for erin expired, and renewing it did not work. Sign in again.',
    )
  })

  it('has its own title and a next step for every kind of failure, and never apologises', () => {
    const failures: Failure[] = [
      { kind: 'unauthorised' },
      { kind: 'rate_limited', retryAfterSeconds: 3 },
      { kind: 'unavailable', reference: 'r' },
      { kind: 'not_found' },
      { kind: 'rejected', status: 422 },
      { kind: 'network' },
      { kind: 'contract' },
      { kind: 'page' },
      { kind: 'cancelled' },
    ]
    const words = failures.map((failure) => describeFailure(failure, 'dave'))

    expect(new Set(words.map((word) => word.title)).size).toBe(failures.length)
    for (const word of words) {
      expect(word.detail).toMatch(/\.$/)
      expect(`${word.title} ${word.detail}`).not.toMatch(/sorry|oops|something went wrong|unfortunately/i)
    }
  })
})

describe('OUTCOME_WORDS', () => {
  it('says something different for each outcome the server can return', () => {
    const titles = OUTCOMES.map((outcome) => OUTCOME_WORDS[outcome].title)

    expect(new Set(titles).size).toBe(OUTCOMES.length)
  })
})

describe('describeRedactions', () => {
  it('lists what was removed, in words', () => {
    expect(describeRedactions({ IBAN: 1, EMAIL: 2 })).toBe('1 IBAN and 2 email addresses')
    expect(describeRedactions({ IBAN: 2, CARD: 1, PHONE: 1 })).toBe('2 IBANs, 1 card number, and 1 phone number')
    expect(describeRedactions({ TCKN: 1 })).toBe('1 Turkish national id')
    expect(describeRedactions({ BSN: 3 })).toBe('3 Dutch citizen service numbers')
  })

  it('is null when nothing was removed', () => {
    expect(describeRedactions({})).toBeNull()
    expect(describeRedactions({ IBAN: 0 })).toBeNull()
  })

  it('keeps the server label for a kind this page has no name for', () => {
    expect(describeRedactions({ PASSPORT: 1 })).toBe('1 PASSPORT')
  })
})
