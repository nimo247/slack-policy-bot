import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from policy_bot.assistant import AnswerError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"


class GroqRuntime:
    """Translate the assistant's Converse messages to Groq chat completions."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def converse(self, *, modelId, messages, system, toolConfig, inferenceConfig):
        payload = {
            "model": modelId,
            "messages": [
                {"role": "system", "content": item["text"]} for item in system
            ],
            "max_completion_tokens": inferenceConfig["maxTokens"],
            "temperature": inferenceConfig["temperature"],
        }
        if toolConfig["tools"]:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": spec["name"],
                        "description": spec["description"],
                        "parameters": spec["inputSchema"]["json"],
                    },
                }
                for spec in (item["toolSpec"] for item in toolConfig["tools"])
            ]
        for message in messages:
            payload["messages"].extend(chat_messages(message))
        request = Request(
            GROQ_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "slack-policy-bot/1.0",
            },
            method="POST",
        )
        request.add_unredirected_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urlopen(request, timeout=25) as response:
                choice = json.load(response)["choices"][0]
            return converse_reply(choice)
        except HTTPError as error:
            code = groq_error_code(error)
            suffix = f" ({code})" if code else ""
            raise AnswerError(f"Groq returned HTTP {error.code}{suffix}.") from error
        except (URLError, TimeoutError) as error:
            raise AnswerError("The Groq request could not complete.") from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise AnswerError("Groq returned an invalid model response.") from error


def groq_error_code(error):
    try:
        details = json.loads(error.read(8192))["error"]
        code = details.get("code") or details.get("type")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", code):
        return code
    return None


def chat_messages(message):
    blocks = message["content"]
    if all("toolResult" in block for block in blocks):
        return [
            {
                "role": "tool",
                "tool_call_id": result["toolUseId"],
                "content": json.dumps(result["content"][0]["json"], ensure_ascii=False),
            }
            for result in (block["toolResult"] for block in blocks)
        ]

    text = "\n".join(block["text"] for block in blocks if "text" in block)
    calls = [
        {
            "id": call["toolUseId"],
            "type": "function",
            "function": {"name": call["name"], "arguments": json.dumps(call["input"])},
        }
        for call in (block["toolUse"] for block in blocks if "toolUse" in block)
    ]
    converted = {"role": message["role"], "content": text or None}
    if calls:
        converted["tool_calls"] = calls
    return [converted]


def converse_reply(choice):
    message = choice["message"]
    blocks = [{"text": message["content"]}] if message.get("content") else []
    for call in message.get("tool_calls", []):
        arguments = json.loads(call["function"]["arguments"])
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object.")
        blocks.append(
            {
                "toolUse": {
                    "toolUseId": call["id"],
                    "name": call["function"]["name"],
                    "input": arguments,
                }
            }
        )
    reason = choice["finish_reason"]
    return {
        "stopReason": {"stop": "end_turn", "tool_calls": "tool_use"}.get(
            reason, reason
        ),
        "output": {"message": {"role": "assistant", "content": blocks}},
    }
