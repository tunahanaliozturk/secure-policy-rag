"""Checks on the model's answer before anyone sees it. The model is not trusted to have followed its rules.

* Every citation must name a chunk retrieved for this user in this request. A citation to anything else is either
  invented or planted by an injected instruction ("cite SEC-004#1"), and either way the answer is not backed.
* An answer must cite at least one chunk.
* Every link must appear verbatim in a retrieved excerpt and point at an allowed host. The first rule stops the model
  inventing links; the second stops a poisoned document from getting its own phishing link repeated, and stops data
  being smuggled out in a query string, which changes the URL and so fails the first rule anyway.

A failed check blocks the whole answer rather than trimming it: a half-cited answer is not something to repair in
code. The failure is audited with its reasons.
"""

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

_ID = r"[A-Z]{2,5}-\d{3}#\d+"
_CITATION = re.compile(rf"\[({_ID}(?:\s*[,;]\s*{_ID})*)\]")  # [CR-001#2] or [CR-001#2, CR-003#1]
# http(s)://, scheme-relative //host (a Markdown link renders it on the page's scheme), or a bare www. host.
_URL = re.compile(r"""(?:(?:https?:)?//|www\.)[^\s<>"'\])]+""", re.IGNORECASE)


@dataclass(frozen=True)
class Verdict:
    cited: tuple[str, ...]
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def urls(text: str) -> list[str]:
    return [u.rstrip(".,;:") for u in _URL.findall(text)]


LINK_REMOVED = "[link removed]"


def withhold_links(text: str, allowed_hosts: Collection[str]) -> str:
    """``text`` with every link to a host outside the allow-list replaced by a marker. For source text shown to a
    reader as it is, where there is no answer to block: the same pattern finds the links and the same allow-list
    judges them as in :func:`check`, so an excerpt cannot show a link that an answer citing it would be blocked for."""

    def judged(match: re.Match[str]) -> str:
        url = match.group().rstrip(".,;:")
        return (url if host(url) in allowed_hosts else LINK_REMOVED) + match.group()[len(url) :]

    return _URL.sub(judged, text)


def citations(text: str) -> tuple[str, ...]:
    return tuple(_unique(i for group in _CITATION.findall(text) for i in re.findall(_ID, group)))


def check(answer: str, retrieved: dict[str, str], allowed_hosts: Collection[str]) -> Verdict:
    """``retrieved`` maps each chunk id retrieved for this request to its text."""
    cited = citations(answer)
    violations: list[str] = []
    if not cited:
        violations.append("no_citation")
    violations.extend(f"unretrieved_citation:{c}" for c in cited if c not in retrieved)
    source_urls = {u for text in retrieved.values() for u in urls(text)}
    for url in urls(answer):
        if url not in source_urls:
            violations.append(f"url_not_in_sources:{host(url)}")
        elif host(url) not in allowed_hosts:
            violations.append(f"url_host_not_allowed:{host(url)}")
    return Verdict(cited, tuple(_unique(violations)))


def host(url: str) -> str:
    return (urlsplit(f"//{url}" if url.lower().startswith("www.") else url).hostname or "").lower()


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))
