import asyncio
import logging
from collections import OrderedDict
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from policy_bot.assistant import AnswerError, NoticeAssistant
from policy_bot.documents import answer_docx
from policy_bot.pdf import MAX_PDF_BYTES, InputError, extract_notice

LOG = logging.getLogger(__name__)


async def download_pdf(
    slack: AsyncWebClient, http: aiohttp.ClientSession, file_id: str
) -> bytes:
    response = await slack.files_info(file=file_id)
    file = response["file"]
    if (
        file.get("mode") == "external"
        or file.get("is_external")
        or file.get("mimetype") != "application/pdf"
    ):
        raise InputError("Please upload a PDF directly to Slack.")
    if file.get("size", 0) > MAX_PDF_BYTES:
        raise InputError("Please upload a PDF that is 2 MB or smaller.")

    url = file.get("url_private_download") or file.get("url_private") or ""
    address = urlsplit(url)
    if (
        address.scheme != "https"
        or address.netloc != "files.slack.com"
        or not address.path.startswith("/files-pri/")
    ):
        raise InputError("I couldn't find a Slack-hosted download for this attachment.")

    headers = {"Authorization": f"Bearer {slack.token}"}
    async with http.get(url, headers=headers, allow_redirects=False) as download:
        if download.status != 200:
            raise InputError(
                "I couldn't download the PDF from Slack. Please upload it again."
            )
        data = bytearray()
        async for chunk in download.content.iter_chunked(64 * 1024):
            data.extend(chunk)
            if len(data) > MAX_PDF_BYTES:
                raise InputError("Please upload a PDF that is 2 MB or smaller.")
    return bytes(data)


class DirectMessages:
    def __init__(self, assistant: NoticeAssistant, http: aiohttp.ClientSession) -> None:
        self.assistant = assistant
        self.http = http
        self.received: OrderedDict[str, None] = OrderedDict()
        self.parallel = asyncio.Semaphore(4)

    async def handle(
        self, event: dict[str, Any], body: dict[str, Any], client: AsyncWebClient
    ) -> None:
        if (
            event.get("channel_type") != "im"
            or event.get("bot_id")
            or not event.get("user")
        ):
            return
        if event.get("subtype") not in (None, "file_share"):
            return

        channel = event["channel"]
        thread = event.get("thread_ts") or event["ts"]
        event_id = body["event_id"]
        if event_id in self.received:
            return
        self.received[event_id] = None
        if len(self.received) > 2048:
            self.received.popitem(last=False)

        async with self.parallel:
            attach_document = False
            try:
                answer = await self._answer(event, client, event_id)
                attach_document = True
            except (InputError, AnswerError) as error:
                answer = str(error)
            except Exception as error:
                LOG.error(
                    "request=%s answer=failed error=%s", event_id, type(error).__name__
                )
                answer = "I couldn't process that request. Please try again shortly."

        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread,
            text=answer,
            mrkdwn=False,
            unfurl_links=False,
            unfurl_media=False,
        )
        LOG.info("request=%s slack=reply", event_id)
        if attach_document:
            try:
                document = await asyncio.to_thread(
                    answer_docx, event["text"].strip(), answer
                )
                await client.files_upload_v2(
                    file=document,
                    filename="academic-policy-answer.docx",
                    title="Academic Policy Answer",
                    channel=channel,
                    thread_ts=thread,
                    request_file_info=False,
                )
                LOG.info("request=%s slack=docx", event_id)
            except Exception as error:
                LOG.warning(
                    "request=%s slack=docx_failed error=%s",
                    event_id,
                    type(error).__name__,
                )

    async def _answer(
        self, event: dict[str, Any], client: AsyncWebClient, event_id: str
    ) -> str:
        attachments = event.get("files") or []
        question = event.get("text", "").strip()
        if len(attachments) != 1 or not question:
            raise InputError(
                "Send one text-based PDF and your question together in the same message."
            )
        if len(question) > 500:
            raise InputError("Please keep your question under 500 characters.")

        data = await download_pdf(client, self.http, attachments[0]["id"])
        pages = await asyncio.to_thread(extract_notice, data)
        LOG.info("request=%s slack=pdf pages=%s", event_id, len(pages))
        return await self.assistant.answer(question, pages, event_id)


def create_app(token: str, handler: DirectMessages) -> AsyncApp:
    app = AsyncApp(token=token)
    app.event("message")(handler.handle)
    return app
