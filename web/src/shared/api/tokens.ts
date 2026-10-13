// Bearer tokens, by person, in this module's memory and nowhere else: not in localStorage or sessionStorage, where a
// script injected later could read them, and gone when the page is reloaded (ADR 0011). No schema library is imported
// here, so the page shell can clear tokens on sign-out without pulling one into the first chunk.

const held = new Map<string, { token: string; until: number }>()

/** A token is treated as expired this long before the server would refuse it, so a request never leaves with one
 *  that dies on the way. */
const EARLY_MS = 30_000

export function heldToken(subject: string): string | null {
  const entry = held.get(subject)
  return entry !== undefined && entry.until - Date.now() > EARLY_MS ? entry.token : null
}

export function holdToken(subject: string, token: string, until: number): void {
  held.set(subject, { token, until })
}

export function forgetTokens(): void {
  held.clear()
}
