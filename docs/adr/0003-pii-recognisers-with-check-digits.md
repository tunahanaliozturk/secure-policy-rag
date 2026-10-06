# 3. PII detection with patterns and check digits, not Presidio

Status: Accepted, 2026-10-06

## Context

Questions and answers must not carry personal data to the model, to logs or to the audit trail. The identifiers that
matter most in a Dutch and Turkish banking context are IBANs, card numbers, the Turkish national id (TCKN), the Dutch
citizen service number (BSN), email addresses and phone numbers. Microsoft Presidio (MIT) was the obvious candidate.
Checked on 2026-10-06, presidio-analyzer 2.2.364 pins `numpy<2.5.0`, which conflicts with the current numpy 2.5.3. It
needs a spaCy language model that is downloaded outside PyPI, and so outside `uv.lock`. Its URL support depends on
tldextract, which fetches the public suffix list over the network by default. It ships a TCKN recogniser but no BSN one.

## Decision

We write our own recognisers: a regular expression per identifier, confirmed by the identifier's own check digit where
one exists (IBAN mod-97, Luhn for cards, the two TCKN check digits, the BSN 11-test). Redaction replaces each match with
a typed, numbered placeholder such as `[IBAN_1]` and is one-way.

## Consequences

- About 150 lines, no model, no network, deterministic, and fully tested offline (`tests/unit/test_pii.py`), including
  the claim that no number in the corpus's policy text is mistaken for personal data.
- Check digits cut false positives sharply but not to zero. By construction a random digit string of the right shape
  passes Luhn one time in ten and mod-97 one time in 97.
- **Names, street addresses and dates of birth are not detected.** That is the cost of having no language model, and it
  is the largest gap in the privacy story (docs/threat-model.md).
- One-way redaction means the model cannot address a customer by name or quote their IBAN back. A policy assistant never
  needs to.
- The sentinel test that pushes personal data through the whole pipeline found a real bug on its first run: a BSN at
  the end of a sentence was missed because the pattern refused a following full stop. Fixed, with a unit test.

## Alternatives

- **Presidio with spaCy.** Finds names. Lost on the numpy conflict, the unlocked model download and the network call;
  it would win once those are fixed, layered in front of these recognisers.
- **Reversible placeholders** (a vault mapping `[IBAN_1]` back to the value). Needed when the answer must contain the
  value, as in a payment assistant. Lost because nothing here needs it, and a vault is one more store of personal data
  to protect.
