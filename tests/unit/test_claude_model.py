"""The Claude adapter, offline: a mock transport stands in for the Messages API, so the test checks the request this
code sends and how it reads the reply. It cannot say anything about how a real model answers."""

import json
from typing import Any

import anthropic
import httpx2
import pytest

from secure_policy_rag import prompt
from secure_policy_rag.model import ClaudeModel, Draft, ModelOutputError

pytestmark = pytest.mark.asyncio(loop_scope="session")

PROMPT = prompt.build(
    "How many leave days?", (prompt.Excerpt("HR-002#1", "HR-002", "Leave", "1", "25 days.", "internal"),)
)


def reply(stop_reason: str, text: str | None, model: str = "claude-sonnet-5-5") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [] if text is None else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 812, "output_tokens": 41},
    }


def model_answering(body: dict[str, Any], seen: list[dict[str, Any]]) -> ClaudeModel:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=body)

    client = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return ClaudeModel(client, "claude-sonnet-5-5", "medium")


async def test_the_request_uses_a_json_schema_and_none_of_the_parameters_current_models_reject() -> None:
    seen: list[dict[str, Any]] = []
    draft = '{"status": "answered", "answer": "25 days [HR-002#1]."}'
    generation = await model_answering(reply("end_turn", draft), seen).generate(PROMPT)

    request = seen[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["effort"] == "medium"
    assert not {"temperature", "top_p", "top_k", "tool_choice", "tools"} & request.keys()
    assert request["system"] == prompt.SYSTEM
    assert generation.draft == Draft(status="answered", answer="25 days [HR-002#1].")
    assert (generation.model, generation.input_tokens, generation.output_tokens) == ("claude-sonnet-5-5", 812, 41)


async def test_a_safety_refusal_comes_back_as_no_draft_rather_than_an_error() -> None:
    generation = await model_answering(reply("refusal", None), []).generate(PROMPT)
    assert generation.draft is None


@pytest.mark.parametrize(
    "body",
    [
        reply("max_tokens", '{"status": "answered", "answ'),
        reply("end_turn", '{"status": "maybe", "answer": "x"}'),
        reply("end_turn", None),
    ],
    ids=["cut-off", "outside-schema", "no-text"],
)
async def test_output_that_cannot_be_trusted_raises(body: dict[str, Any]) -> None:
    with pytest.raises(ModelOutputError):
        await model_answering(body, []).generate(PROMPT)
