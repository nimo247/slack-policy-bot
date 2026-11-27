import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from policy_bot.assistant import NoticeAssistant
from policy_bot.pdf import extract_notice
from policy_bot.policy_client import open_policy_session

DEFAULT_MODEL = "amazon.nova-lite-v1:0"
DEFAULT_REGION = "us-east-1"


def create_runtime():
    import boto3
    from botocore.config import Config

    region = (
        os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or DEFAULT_REGION
    )
    config = Config(
        connect_timeout=5,
        read_timeout=25,
        retries={"mode": "standard", "total_max_attempts": 2},
    )
    return boto3.client("bedrock-runtime", region_name=region, config=config)


def configured_runtime():
    provider = os.getenv("POLICY_BOT_PROVIDER", "bedrock")
    if provider == "bedrock":
        return provider, create_runtime(), os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL)
    if provider == "groq":
        from policy_bot.groq_runtime import DEFAULT_GROQ_MODEL, GroqRuntime

        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise SystemExit("Set GROQ_API_KEY to use the Groq provider.")
        return (
            provider,
            GroqRuntime(key),
            os.getenv("GROQ_MODEL_ID", DEFAULT_GROQ_MODEL),
        )
    raise SystemExit("Set POLICY_BOT_PROVIDER to bedrock or groq.")


async def run_slack() -> None:
    import aiohttp
    from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler

    from policy_bot.slack_app import DirectMessages, create_app

    app_token = os.getenv("SLACK_APP_TOKEN", "")
    bot_token = os.getenv("SLACK_BOT_TOKEN", "")
    if not app_token.startswith("xapp-") or not bot_token.startswith("xoxb-"):
        raise SystemExit(
            "Set SLACK_APP_TOKEN and SLACK_BOT_TOKEN in your environment or .env file."
        )

    provider, runtime, model_id = configured_runtime()
    async with open_policy_session() as (session, tool):
        assistant = NoticeAssistant(runtime, model_id, session, tool, provider=provider)
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as http:
            app = create_app(bot_token, DirectMessages(assistant, http))
            socket = AsyncSocketModeHandler(app, app_token)
            try:
                await socket.start_async()
            finally:
                await socket.close_async()


async def ask_pdf(path: Path, question: str) -> None:
    pages = extract_notice(path.read_bytes())
    provider, runtime, model_id = configured_runtime()
    async with open_policy_session() as (session, tool):
        assistant = NoticeAssistant(runtime, model_id, session, tool, provider=provider)
        print(await assistant.answer(question, pages, "terminal"))


async def check_mcp() -> None:
    async with open_policy_session() as (session, tool):
        result = await session.call_tool(
            tool.name, {"query": "Embedded Systems Lab prerequisite"}
        )
        if result.isError or not result.structuredContent:
            raise SystemExit("MCP tool did not return a result.")
        print(f"Discovered {tool.name}")
        for match in result.structuredContent["matches"]:
            print(f"[{match['id']}] {match['excerpt']}")


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Slack PDF assistant")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "demo", help="Run the sample PDF workflow with a scripted model and live MCP"
    )
    commands.add_parser("check-mcp", help="Run a live local MCP lookup")
    commands.add_parser(
        "check-bedrock", help="Make a minimal authenticated Bedrock request"
    )
    ask = commands.add_parser(
        "ask", help="Ask about a local PDF with the configured model and MCP"
    )
    ask.add_argument("pdf", type=Path)
    ask.add_argument("question")
    args = parser.parse_args()
    if args.command == "check-mcp":
        asyncio.run(check_mcp())
    elif args.command == "demo":
        from policy_bot.demo import run_demo

        asyncio.run(run_demo())
    elif args.command == "check-bedrock":
        response = create_runtime().converse(
            modelId=os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL),
            messages=[
                {"role": "user", "content": [{"text": "Reply with the word OK."}]}
            ],
            inferenceConfig={"maxTokens": 32, "temperature": 0},
        )
        print(response["output"]["message"]["content"][0]["text"])
    elif args.command == "ask":
        asyncio.run(ask_pdf(args.pdf, args.question))
    else:
        asyncio.run(run_slack())


if __name__ == "__main__":
    main()
