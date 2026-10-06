"""Policy documents on disk, and the chunks they become.

A document is a Markdown file with a small header block::

    ---
    id: CR-001
    title: Retail Credit Policy
    department: credit
    classification: internal
    ---

Each ``## `` section becomes one chunk: section 2 of CR-001 is ``CR-001#2``. Policies are written in short numbered
sections already, so a section is the natural unit to retrieve and to cite; a 2,000-word section would make one
oversized chunk, and splitting it is left until a document like that exists.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from secure_policy_rag.identity import DEPARTMENTS, Clearance

_HEADER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_ID = re.compile(r"^[A-Z]{2,5}-\d{3}$")


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    title: str
    heading: str
    text: str
    department: str
    classification: Clearance

    def for_embedding(self) -> str:
        return f"{self.title}. {self.heading}. {self.text}"


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    department: str
    classification: Clearance
    body: str

    def chunks(self) -> list[Chunk]:
        chunks: list[Chunk] = []
        # Part 0 is whatever precedes the first section: the title line, and sometimes a control code.
        for number, section in enumerate(re.split(r"^## +", self.body, flags=re.MULTILINE)):
            heading, _, text = section.partition("\n")
            text = " ".join(text.split())
            if not text:
                continue
            heading = "Document control" if number == 0 else heading.strip()
            chunk_id = f"{self.id}#{number}"
            chunks.append(Chunk(chunk_id, self.id, self.title, heading, text, self.department, self.classification))
        return chunks


class CorpusError(ValueError):
    pass


def parse(text: str, source: str = "<text>") -> Document:
    match = _HEADER.match(text.replace("\r\n", "\n"))
    if match is None:
        raise CorpusError(f"{source}: missing the --- header block")
    fields = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    fields = {k.strip(): v.strip() for k, v in fields.items()}
    try:
        document = Document(
            id=fields["id"],
            title=fields["title"],
            department=fields["department"],
            classification=Clearance.parse(fields["classification"]),
            body=text.replace("\r\n", "\n")[match.end() :],
        )
    except KeyError as missing:
        raise CorpusError(f"{source}: header field missing or not recognised: {missing}") from None
    if not _ID.match(document.id) or document.department not in DEPARTMENTS:
        raise CorpusError(f"{source}: bad id {document.id!r} or department {document.department!r}")
    return document


def load(directory: Path) -> list[Document]:
    documents = [parse(p.read_text(encoding="utf-8"), p.name) for p in sorted(directory.glob("*.md"))]
    ids = [d.id for d in documents]
    if len(ids) != len(set(ids)):
        raise CorpusError("duplicate document ids")
    return documents
