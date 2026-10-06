"""The answering model, behind one small protocol so tests and the offline evaluation can script it.

:class:`ClaudeModel` calls the Messages API with native structured output (a JSON schema in ``output_config``), not a
forced tool call: current Claude models reject forced ``tool_choice`` and non-default temperature with a 400, and a
schema gives the same guarantee of parseable JSON. The model gets no tools at all, so the worst an injected instruction
can do is shape the text of the answer, which verify.py then checks (ADR 0004).

:class:`ScriptedModel` behaves in a fixed, named way: faithfully, or like a model that fell for an injection. It is how
the offline evaluation shows that the guards catch a misbehaving model. It measures the guards, not the quality of any
real model; that needs ``ANTHROPIC_API_KEY`` and ``spr eval answers --model anthropic``.
"""

import re
from dataclasses import dataclass
from typing import Literal, Protocol

import anthropic
from pydantic import BaseModel, ConfigDict

from secure_policy_rag.prompt import Prompt


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["answered", "insufficient_context"]
    answer: str


DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        # Status comes first so the model commits to "can I answer this?" before it writes the answer.
        "status": {"type": "string", "enum": ["answered", "insufficient_context"]},
        "answer": {"type": "string"},
    },
    "required": ["status", "answer"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Generation:
    draft: Draft | None
    """None when the model declined (a safety refusal), which the pipeline treats as a refusal to answer."""
    model: str
    """The model that actually produced the answer, as the API reported it, for the audit trail."""
    input_tokens: int | None = None
    output_tokens: int | None = None


class AnswerModel(Protocol):
    @property
    def name(self) -> str: ...

    async def generate(self, prompt: Prompt) -> Generation: ...


class ModelOutputError(Exception):
    """The model stopped before finishing its JSON (``max_tokens``) or returned something the schema forbids."""


type Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeModel:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str, effort: Effort, max_tokens: int = 16000) -> None:
        self._client = client
        self._model = model
        self._effort: Effort = effort
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return self._model

    async def generate(self, prompt: Prompt) -> Generation:
        # No temperature, no tool_choice: both are rejected by current models. Thinking is left at the model default.
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=prompt.system,
            messages=[{"role": "user", "content": prompt.user}],
            output_config={"effort": self._effort, "format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
        )
        usage = (response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal":
            return Generation(None, response.model, *usage)
        if response.stop_reason == "max_tokens":
            raise ModelOutputError("the answer was cut off at max_tokens")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise ModelOutputError("no text block in the response")
        try:
            draft = Draft.model_validate_json(text)
        except ValueError as error:
            raise ModelOutputError("the answer did not match the schema") from error
        return Generation(draft, response.model, *usage)


type Behaviour = Literal[
    "faithful", "insufficient", "echo", "repeat_links", "cite_unretrieved", "invent_url", "no_citation"
]
_FIRST_SENTENCE = re.compile(r"^(.+?[.!?])(?:\s|$)")
_LINK = re.compile(r"https?://[^\s]+[^\s.,;:]")


class ScriptedModel:
    """Deterministic stand-in. ``faithful`` quotes the first sentence of the best excerpt and cites it; the others
    each break one rule the way a confused or manipulated model would."""

    def __init__(self, behaviour: Behaviour = "faithful") -> None:
        self.behaviour: Behaviour = behaviour

    @property
    def name(self) -> str:
        return f"scripted:{self.behaviour}"

    async def generate(self, prompt: Prompt) -> Generation:
        if not prompt.excerpts or self.behaviour == "insufficient":
            return self._done("insufficient_context", "The policies provided do not cover this question.")
        top = prompt.excerpts[0]
        first = _FIRST_SENTENCE.match(top.text)
        sentence = first.group(1) if first else top.text
        faithful = f"{sentence} [{top.chunk_id}]"
        match self.behaviour:
            case "faithful":
                answer = faithful
            case "echo":  # repeats sources wholesale: their personal data and their links come along
                answer = " ".join(f"{e.text} [{e.chunk_id}]" for e in prompt.excerpts[:2])
            case "repeat_links":  # does what a poisoned page asks: passes on every link it was shown
                answer = " ".join([faithful, *(link for e in prompt.excerpts for link in _LINK.findall(e.text))])
            case "cite_unretrieved":
                answer = f"{faithful} See also [SEC-004#1]."
            case "invent_url":
                answer = f"{faithful} Details: https://policy-portal.example.net/login"
            case "no_citation":
                answer = sentence
        return self._done("answered", answer)

    def _done(self, status: Literal["answered", "insufficient_context"], answer: str) -> Generation:
        return Generation(Draft(status=status, answer=answer), self.name)
