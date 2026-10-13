/**
 * Three questions the six demo people get different results for, on the corpus in this repository with the default
 * retrieval settings. The first two split on clearance and department; the third carries an IBAN and an email address,
 * so it shows redaction. The journeys in e2e/ assert on the first and the third against the real stack.
 */
export const EXAMPLES = [
  'Which systems are the crown jewel systems?',
  'How soon must an unusual transaction be reported to the Financial Intelligence Unit?',
  'My IBAN is NL91 ABNA 0417 1643 00 and my email is me@example.com. May I work from home?',
] as const
