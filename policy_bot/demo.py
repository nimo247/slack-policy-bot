from pathlib import Path

from policy_bot.assistant import NoticeAssistant
from policy_bot.pdf import extract_notice
from policy_bot.policy_client import open_policy_session

QUESTION = "What prerequisite do I need for Embedded Systems Lab?"
SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample-lab-notice.pdf"


class ScriptedRuntime:
    """Simulate the model's decision for the included sample notice."""

    def converse(self, *, messages, toolConfig, **kwargs):
        if len(messages) == 1:
            blocks = [
                {
                    "toolUse": {
                        "toolUseId": "demo-policy-lookup",
                        "name": toolConfig["tools"][0]["toolSpec"]["name"],
                        "input": {"query": "Embedded Systems Lab prerequisite"},
                    }
                }
            ]
            reason = "tool_use"
        else:
            matches = messages[-1]["content"][0]["toolResult"]["content"][0]["json"][
                "matches"
            ]
            text = (
                f"{matches[0]['excerpt']} [{matches[0]['id']}]"
                if matches
                else "NO_EVIDENCE"
            )
            blocks = [{"text": text}]
            reason = "end_turn"
        return {
            "stopReason": reason,
            "output": {"message": {"role": "assistant", "content": blocks}},
        }


async def run_demo() -> None:
    print(
        "Offline demo. Model responses are scripted. PDF extraction and MCP are live.",
        flush=True,
    )
    pages = extract_notice(SAMPLE.read_bytes())
    print(f"PDF: {SAMPLE.name} ({len(pages)} page extracted)", flush=True)
    print(f"Question: {QUESTION}", flush=True)
    async with open_policy_session() as (session, tool):
        assistant = NoticeAssistant(
            ScriptedRuntime(), "offline", session, tool, provider="scripted_model"
        )
        print(await assistant.answer(QUESTION, pages, "offline-demo"))
