// The journeys the console exists for, against the real stack: nginx, the demo login, the API, and Postgres deciding
// with row-level security what each person may read. The answer model is the scripted stand-in, so every assertion
// here is about sources and access, never about the quality of an answer.

import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Locator, type Page } from '@playwright/test'

const PASSWORD = 'How long must my password be?'
const CROWN_JEWELS = 'Which systems are the crown jewel systems?'
const WITH_PERSONAL_DATA = 'My IBAN is NL91 ABNA 0417 1643 00 and my email is me@example.com. May I work from home?'
const RUNBOOK = 'SEC-004#2' // security, restricted: only erin is in security with restricted clearance

const asked = (question: string): string => `/ask?q=${encodeURIComponent(question)}`

// The page is served with `default-src 'self'` and must run under it without tripping it. A blocked inline style or
// an eval attempt does not break a journey, so nothing else here would notice one: every journey ends by checking that
// the browser reported no violation. (Lighthouse found one this way: the schema library probing for eval.)
let violations: string[] = []

test.beforeEach(async ({ page }) => {
  violations = []
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (event) => {
      console.error(`CSP-VIOLATION ${event.violatedDirective} ${event.blockedURI}`)
    })
  })
  page.on('console', (message) => {
    if (/CSP-VIOLATION|Content[- ]Security[- ]Policy/i.test(message.text())) violations.push(message.text())
  })
})

test.afterEach(() => {
  expect(violations, 'content security policy violations reported by the browser').toEqual([])
})

async function signInAs(page: Page, name: string): Promise<void> {
  await page.getByRole('button', { name: `Sign in as ${name}` }).click()
  await expect(page.getByText(`Signed in as ${name}`)).toBeVisible()
}

async function expectNoAxeViolations(page: Page): Promise<void> {
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
}

/** Presses Tab (or Shift+Tab, to go back up the page) until `target` has focus, as someone without a mouse would.
 *  Fails if it is not reachable. */
async function tabTo(page: Page, target: Locator, key: 'Tab' | 'Shift+Tab' = 'Tab'): Promise<void> {
  for (let presses = 0; presses < 40; presses++) {
    if (await target.evaluate((element) => element === document.activeElement).catch(() => false)) return
    await page.keyboard.press(key)
  }
  await expect(target).toBeFocused()
}

/** The table row of one person in the comparison. */
const rowOf = (page: Page, name: string): Locator =>
  page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: new RegExp(`^${name}`) }) })

/** A token for one of the six, straight from the login, for asking the API without the page in between. */
async function tokenFor(page: Page, name: string): Promise<string> {
  const response = await page.request.post('/login/token', { data: { name } })
  expect(response.status()).toBe(200)
  const body: unknown = await response.json()
  if (typeof body !== 'object' || body === null || !('token' in body) || typeof body.token !== 'string') {
    throw new Error('the login did not return a token')
  }
  return body.token
}

test('a person signs in, asks, and gets an answer that cites a source', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Sign in as a member of staff' })).toBeVisible()
  await expect(page.getByText('This is a demonstration with no passwords')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Sign in as / })).toHaveCount(6)
  await expectNoAxeViolations(page)

  await signInAs(page, 'dave')
  await expect(page.getByRole('heading', { level: 1, name: 'Ask the policy library' })).toBeFocused()
  await expect(page).toHaveTitle('Ask | Policy desk')
  await expectNoAxeViolations(page)

  await page.getByRole('textbox', { name: 'Question' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()

  const result = page.getByRole('region', { name: 'Result' })
  await expect(result.getByText('Answered')).toBeVisible()
  await expect(result).toContainText('Passwords for personal accounts must be at least 14 characters long.')
  await expect(result.getByRole('link', { name: /SEC-002#1/ })).toBeVisible()
  await expect(page.getByRole('status').first()).toHaveText('Answered. 1 source cited.')
  // The question is in the address, so the result can be reloaded or sent to someone.
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe(PASSWORD)
  await expectNoAxeViolations(page)

  // The token lives in the page's memory: nothing was written where a later script could read it.
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length, document.cookie])).toEqual([0, 0, ''])
})

test('the same question as six people: erin is answered from the runbook, dave cannot open it', async ({ page }) => {
  await page.goto(`/compare?q=${encodeURIComponent(CROWN_JEWELS)}`)
  const table = page.getByRole('table', { name: 'One question, six readers' })
  await expect(table.getByRole('row')).toHaveCount(7)
  await expect(table.getByText('Checking')).toHaveCount(0)

  // Which sources were cited at all: the restricted runbook, and something everybody may read.
  const runbookColumn = table.getByRole('columnheader', { name: new RegExp(`^${RUNBOOK}`) })
  await expect(runbookColumn).toContainText('Crown jewel systems')
  await expect(runbookColumn).toContainText('restricted')
  await expect(runbookColumn).toContainText('security')

  const erin = rowOf(page, 'erin')
  await expect(erin).toContainText(`[${RUNBOOK}]`)
  await expect(erin).toContainText('The crown jewel systems are the payments hub')
  await expect(erin.getByRole('link', { name: `Cited: open ${RUNBOOK} as erin` })).toBeVisible()

  for (const name of ['alice', 'bob', 'carol', 'dave', 'frank']) {
    const row = rowOf(page, name)
    await expect(row).toContainText('Answered')
    await expect(row).not.toContainText(RUNBOOK)
    await expect(row).not.toContainText('payments hub')
    await expect(row.getByText('No access')).toHaveCount(1)
    await expect(row.getByRole('link', { name: new RegExp(`open ${RUNBOOK}`) })).toHaveCount(0)
  }
  await expect(page.getByRole('status').first()).toHaveText('Asked as 6 people: 6 answered. 2 different sources cited.')
  await expectNoAxeViolations(page)

  // What the page drew is what the server says when asked directly, with each person's own token.
  const path = `/api/excerpts/${encodeURIComponent(RUNBOOK)}`
  const asErin = await page.request.get(path, { headers: { Authorization: `Bearer ${await tokenFor(page, 'erin')}` } })
  const asDave = await page.request.get(path, { headers: { Authorization: `Bearer ${await tokenFor(page, 'dave')}` } })
  expect([asErin.status(), asDave.status()]).toEqual([200, 404])

  // Opening the runbook from erin's mark shows it as erin.
  await erin.getByRole('link', { name: `Cited: open ${RUNBOOK} as erin` }).click()
  const source = page.getByRole('region', { name: `${RUNBOOK} opened as erin` })
  await expect(source).toContainText('Network isolation of a crown jewel system requires approval')
  await expect(page).toHaveURL(/reader=erin/)
  await expectNoAxeViolations(page)
})

test('what was removed from a question is shown, and the question still gets an answer', async ({ page }) => {
  await page.goto('/')
  await signInAs(page, 'frank')

  await page.getByRole('button', { name: WITH_PERSONAL_DATA }).click()

  const result = page.getByRole('region', { name: 'Result' })
  await expect(result).toContainText(
    'Removed from the question before it was searched or sent to the model: 1 IBAN and 1 email address.',
  )
  await expect(result.getByText('Answered')).toBeVisible()
  await expect(result).not.toContainText('NL91')
  await expect(result).not.toContainText('me@example.com')
  await expectNoAxeViolations(page)
})

test('a cited source opens as the person who asked, and closes back to its link', async ({ page }) => {
  await page.goto(asked(CROWN_JEWELS))
  await signInAs(page, 'erin')

  const citation = page.getByRole('link', { name: new RegExp(RUNBOOK) })
  await citation.click()

  const source = page.getByRole('region', { name: `${RUNBOOK} opened as erin` })
  await expect(source.getByRole('heading', { level: 2 })).toBeFocused()
  await expect(source).toContainText('2. Crown jewel systems')
  await expect(source).toContainText('Network isolation of a crown jewel system requires approval')
  await expect(source.getByText('restricted')).toBeVisible()
  await expect(source.getByText('security', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/source=SEC-004%232$/)
  await expectNoAxeViolations(page)

  await source.getByRole('button', { name: 'Close this source' }).click()
  await expect(source).toHaveCount(0)
  await expect(citation).toBeFocused()
})

test('a source the person may not read cannot be opened by editing the address', async ({ page }) => {
  // The address of erin's opened runbook, typed in by someone who then signs in as dave.
  const excerptAnswered = page.waitForResponse((response) => response.url().includes('/api/excerpts/'))
  await page.goto(`${asked(CROWN_JEWELS)}&source=${encodeURIComponent(RUNBOOK)}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Sign in as a member of staff' })).toBeVisible()
  await signInAs(page, 'dave')

  const source = page.getByRole('region', { name: `${RUNBOOK} opened as dave` })
  await expect(source.getByRole('alert')).toContainText(`dave cannot open ${RUNBOOK}`)
  await expect(page.getByText('payments hub')).toHaveCount(0)
  await expect(page.getByText('Network isolation')).toHaveCount(0)
  await expectNoAxeViolations(page)

  // The server's answer for the runbook is byte for byte its answer for a chunk that does not exist.
  const refused = await excerptAnswered
  const headers = { Authorization: `Bearer ${await tokenFor(page, 'dave')}` }
  const absent = await page.request.get('/api/excerpts/SEC-999%232', { headers })
  expect([refused.status(), absent.status()]).toEqual([404, 404])
  expect(await refused.text()).toBe(await absent.text())
})

test('the whole path works with the keyboard alone', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Sign in as erin' })).toBeVisible()

  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to the page content' })).toBeFocused()

  await tabTo(page, page.getByRole('button', { name: 'Sign in as erin' }))
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'Ask the policy library' })).toBeFocused()

  await tabTo(page, page.getByRole('textbox', { name: 'Question' }))
  await page.keyboard.type(CROWN_JEWELS)
  await page.keyboard.press('Enter')
  await expect(page.getByRole('status').first()).toHaveText('Answered. 1 source cited.')

  const citation = page.getByRole('link', { name: new RegExp(RUNBOOK) })
  await tabTo(page, citation)
  await page.keyboard.press('Enter')
  const source = page.getByRole('region', { name: `${RUNBOOK} opened as erin` })
  await expect(source.getByRole('heading', { level: 2 })).toBeFocused()
  await expect(source).toContainText('Network isolation of a crown jewel system requires approval')

  await tabTo(page, source.getByRole('button', { name: 'Close this source' }))
  await page.keyboard.press('Enter')
  await expect(source).toHaveCount(0)
  await expect(citation).toBeFocused()

  // On to the comparison and into its table, still without a mouse.
  await tabTo(page, page.getByRole('link', { name: 'Ask as everyone' }), 'Shift+Tab')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'Ask as everyone' })).toBeFocused()
  await tabTo(page, page.getByRole('button', { name: CROWN_JEWELS }))
  await page.keyboard.press('Enter')
  const mark = page.getByRole('link', { name: `Cited: open ${RUNBOOK} as erin` })
  await tabTo(page, mark)
  await page.keyboard.press('Enter')
  await expect(page.getByRole('region', { name: `${RUNBOOK} opened as erin` })).toContainText('Network isolation')
})

test('a 429 shows how long to wait and a 503 shows the reference to quote', async ({ page }) => {
  await page.goto('/')
  await signInAs(page, 'carol')

  await page.route('**/api/ask', (route) =>
    route.fulfill({
      status: 429,
      contentType: 'application/json',
      headers: { 'Retry-After': '17' },
      body: JSON.stringify({ detail: 'too many requests' }),
    }),
  )
  await page.getByRole('textbox', { name: 'Question' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Too many requests')
  await expect(alert).toContainText('carol has sent too many requests. Wait 17 seconds, then try again.')
  await expect(page.getByRole('region', { name: 'Result' })).toHaveCount(0)
  await expectNoAxeViolations(page)

  await page.unroute('**/api/ask')
  await page.route('**/api/ask', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'the assistant is unavailable', reference: 'e2e-reference-0001' }),
    }),
  )
  await alert.getByRole('button', { name: 'Ask again' }).click()
  await expect(alert).toContainText('The assistant is unavailable')
  await expect(alert).toContainText('If you report this, quote reference e2e-reference-0001.')

  // With the real API back, the same button gets the answer.
  await page.unroute('**/api/ask')
  await alert.getByRole('button', { name: 'Ask again' }).click()
  await expect(page.getByRole('region', { name: 'Result' }).getByText('Answered')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('every response on the one origin carries the security headers, the proxied ones too', async ({ page }) => {
  for (const path of ['/', '/ask', '/favicon.svg', '/healthz', '/api/healthz', '/login/identities', '/api/ask']) {
    const response = await page.request.get(path)
    const headers = response.headers()
    expect(headers['content-security-policy'], path).toBe(
      "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
    )
    expect(headers['x-content-type-options'], path).toBe('nosniff')
    expect(headers['referrer-policy'], path).toBe('no-referrer')
  }
})
