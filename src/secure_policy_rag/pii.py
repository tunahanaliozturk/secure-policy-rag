"""Finding and redacting personal data in free text, with patterns and checksums, no NLP model (ADR 0003).

A pattern alone finds too much in banking text: every 11-digit reference looks like a Turkish national id and every
long number like a card. So each identifier that has a check digit is confirmed by it before it counts. By
construction that lets through one random digit string in ten for Luhn, one in a hundred for the Turkish id, one in
eleven for the BSN and one in 97 for IBAN, and none of the numbers in this corpus's policy text
(tests/unit/test_pii.py). Email addresses and phone numbers have no checksum; their patterns are kept narrow instead.
Names, addresses and dates of birth are not detected at all, which is the main limitation (docs/threat-model.md).

Redaction is one-way: ``NL91ABNA0417164300`` becomes ``[IBAN_1]``. Nothing in this service needs the original back,
because a policy question does not depend on whose account it was.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

type Kind = Literal["IBAN", "CARD", "TCKN", "BSN", "EMAIL", "PHONE"]


@dataclass(frozen=True)
class Finding:
    kind: Kind
    start: int
    end: int


@dataclass(frozen=True)
class Redacted:
    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def iban_valid(candidate: str) -> bool:
    """ISO 13616 mod-97: move the first four characters to the end, letters become 10..35, remainder must be 1."""
    compact = candidate.replace(" ", "").upper()
    if not 15 <= len(compact) <= 34 or not compact.isalnum() or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def luhn_valid(number: str) -> bool:
    digits = [int(d) for d in _digits(number)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, digit in enumerate(reversed(digits)):
        doubled = digit * 2 if i % 2 else digit  # every second digit from the right is doubled
        total += doubled - 9 if doubled > 9 else doubled
    return total % 10 == 0


def tckn_valid(number: str) -> bool:
    """Turkish national id: 11 digits, no leading zero, two check digits computed from the first nine and ten."""
    d = [int(c) for c in number]
    if len(d) != 11 or d[0] == 0:
        return False
    tenth = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return d[9] == tenth and d[10] == sum(d[:10]) % 10


def bsn_valid(number: str) -> bool:
    """Dutch citizen service number, the "11-test": 9*d1 + 8*d2 + ... + 2*d8 - d9 must be a multiple of 11."""
    d = [int(c) for c in _digits(number)]
    if len(d) != 9 or not any(d):
        return False
    return (sum(w * x for w, x in zip(range(9, 1, -1), d[:8], strict=True)) - d[8]) % 11 == 0


def _iban_span(match: re.Match[str]) -> tuple[int, int] | None:
    """The written form groups by four, so the pattern may swallow a following word ("... 4300 AND"). Drop trailing
    groups until the checksum holds, and use the span that does."""
    groups = match.group().split(" ")
    for n in range(len(groups), 0, -1):
        if iban_valid("".join(groups[:n])):
            return match.start(), match.start() + len(" ".join(groups[:n]))
    return None


def _whole(check: Callable[[str], bool]) -> Callable[[re.Match[str]], tuple[int, int] | None]:
    return lambda m: m.span() if check(m.group()) else None


def _always(match: re.Match[str]) -> tuple[int, int]:
    return match.span()


def _phone_length(candidate: str) -> bool:
    return 9 <= len(_digits(candidate)) <= 15


# Order matters: earlier recognisers win an overlap, so the stricter, checksummed ones come first.
_RECOGNISERS: list[tuple[Kind, re.Pattern[str], Callable[[re.Match[str]], tuple[int, int] | None]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"), _always),
    ("IBAN", re.compile(r"\b[A-Za-z]{2}\d{2}(?: ?[A-Za-z0-9]{1,4}){3,8}\b"), _iban_span),
    ("CARD", re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])"), _whole(luhn_valid)),
    ("TCKN", re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)"), _whole(tckn_valid)),
    # A full stop may end the sentence after a BSN; only a dot followed by more digits continues the number.
    ("BSN", re.compile(r"(?<!\d)(?<!\d\.)(?:\d{9}|\d{4}\.\d{2}\.\d{3})(?!\d|\.\d)"), _whole(bsn_valid)),
    # International (+31 6 1234 5678, +90 532 123 45 67) or a national trunk prefix (06-12345678, 0532 123 45 67).
    # Nine to fifteen digits in total, which leaves amounts, dates and policy numbers alone.
    ("PHONE", re.compile(r"(?<![\w+])(?:\+\d{1,3}|0)(?:[ -]?\(?\d{1,4}\)?){2,5}(?!\d)"), _whole(_phone_length)),
]


def find(text: str) -> list[Finding]:
    """Every personal identifier found, in text order, without overlaps."""
    taken: list[Finding] = []
    for kind, pattern, confirm in _RECOGNISERS:
        for match in pattern.finditer(text):
            span = confirm(match)
            if span is None or any(span[0] < f.end and f.start < span[1] for f in taken):
                continue
            taken.append(Finding(kind, *span))
    return sorted(taken, key=lambda f: f.start)


def redact(text: str) -> Redacted:
    """Replace each identifier with a numbered placeholder. The same value gets the same number within one text."""
    findings = find(text)
    numbers: dict[tuple[str, str], int] = {}
    per_kind: Counter[str] = Counter()
    out: list[str] = []
    position = 0
    for f in findings:
        value = text[f.start : f.end]
        key = (f.kind, re.sub(r"[\s.()-]", "", value).lower())
        if key not in numbers:
            per_kind[f.kind] += 1
            numbers[key] = per_kind[f.kind]
        out.append(text[position : f.start])
        out.append(f"[{f.kind}_{numbers[key]}]")
        position = f.end
    out.append(text[position:])
    return Redacted("".join(out), dict(Counter(f.kind for f in findings)))
