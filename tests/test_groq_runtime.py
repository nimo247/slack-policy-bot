import asyncio
import io
import json
from urllib.error import HTTPError

import pytest

from policy_bot.assistant import AnswerError, NoticeAssistant
from policy_bot.demo import QUESTION, SAMPLE
from policy_bot.groq_runtime import DEFAULT_GROQ_MODEL, GroqRuntime
from policy_bot.pdf import extract_notice
from policy_bot.policy_client import TOOL_NAME, open_policy_session


def test_groq_tool_call_roundtrip_with_real_mcp(monkeypatch):
    requests = []

    def fake_endpoint(request, *, timeout):
        payload = json.loads(request.data)
        requests.append(payload)
        assert payload["tools"][0]["function"]["name"] == TOOL_NAME
        assert request.get_header("Authorization") == "Bearer testing"
        assert request.get_header("User-agent") == "slack-policy-bot/1.0"
        assert "tool_choice" not in payload
        if len(requests) == 1:
            choice = {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": TOOL_NAME,
                                "arguments": json.dumps(
                                    {"query": "Embedded Systems Lab prerequisite"}
                                ),
                            },
                        }
                    ],
                },
            }
        else:
            assistant, result = payload["messages"][-2:]
            assert (
                assistant["tool_calls"][0]["id"] == result["tool_call_id"] == "call_1"
            )
            match = json.loads(result["content"])["matches"][0]
            assert match["id"] == "LAB-101"
            choice = {
                "finish_reason": "stop",
                "message": {"content": f"{match['excerpt']} [{match['id']}]"},
            }
        return io.BytesIO(json.dumps({"choices": [choice]}).encode())

    monkeypatch.setattr("policy_bot.groq_runtime.urlopen", fake_endpoint)

    async def exercise():
        async with open_policy_session() as (session, tool):
            assistant = NoticeAssistant(
                GroqRuntime("testing"),
                DEFAULT_GROQ_MODEL,
                session,
                tool,
                provider="groq",
            )
            return await assistant.answer(
                "What do I need before taking this lab?",
                extract_notice(SAMPLE.read_bytes()),
                "test-groq",
            )

    answer = asyncio.run(exercise())
    assert len(requests) == 2
    assert "Digital Logic" in answer
    assert "[LAB-101] Embedded Systems Lab prerequisite" in answer


@pytest.mark.parametrize(
    "notice_name", ["sample-lab-notice.pdf", "sample-injection-notice.pdf"]
)
def test_groq_receives_retrieved_policy_in_a_plain_request(monkeypatch, notice_name):
    requests = []
    notice_pages = extract_notice(SAMPLE.with_name(notice_name).read_bytes())

    def fake_endpoint(request, *, timeout):
        payload = json.loads(request.data)
        requests.append(payload)
        assert "tools" not in payload and "tool_choice" not in payload
        prompt = json.loads(payload["messages"][1]["content"])
        assert prompt["question"] == QUESTION
        assert prompt["notice_pages"] == notice_pages
        (policy,) = prompt["handbook_policies"]
        assert policy["id"] == "LAB-101"
        answer = f"{policy['excerpt']} [{policy['id']}]"
        return io.BytesIO(
            json.dumps(
                {"choices": [{"finish_reason": "stop", "message": {"content": answer}}]}
            ).encode()
        )

    monkeypatch.setattr("policy_bot.groq_runtime.urlopen", fake_endpoint)

    async def exercise():
        async with open_policy_session() as (session, tool):
            assistant = NoticeAssistant(
                GroqRuntime("testing"),
                DEFAULT_GROQ_MODEL,
                session,
                tool,
                provider="groq",
            )
            return await assistant.answer(QUESTION, notice_pages, "test-groq")

    answer = asyncio.run(exercise())
    assert len(requests) == 1
    assert "must pass Digital Logic" in answer
    assert "[LAB-101]" in answer


def test_groq_error_reports_the_code_without_the_generation(monkeypatch):
    def reject(request, *, timeout):
        body = b'{"error":{"code":"tool_use_failed","failed_generation":"PRIVATE"}}'
        raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(body))

    monkeypatch.setattr("policy_bot.groq_runtime.urlopen", reject)
    with pytest.raises(AnswerError) as error:
        GroqRuntime("testing").converse(
            modelId=DEFAULT_GROQ_MODEL,
            messages=[{"role": "user", "content": [{"text": "Example question"}]}],
            system=[],
            toolConfig={"tools": []},
            inferenceConfig={"maxTokens": 100, "temperature": 0},
        )
    assert str(error.value) == "Groq returned HTTP 400 (tool_use_failed)."
