from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

MAX_PDF_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 12
MAX_NOTICE_CHARS = 16_000


class InputError(ValueError):
    """A problem the person uploading the notice can correct."""


def extract_notice(data: bytes) -> dict[str, str]:
    if len(data) > MAX_PDF_BYTES:
        raise InputError("Please upload a PDF that is 2 MB or smaller.")
    if not data.startswith(b"%PDF-"):
        raise InputError("The attachment does not appear to be a PDF.")

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise InputError("Please upload an unlocked PDF.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise InputError("Please upload a PDF with 12 pages or fewer.")
        pages = {}
        total = 0
        for number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text().strip()
            total += len(page_text)
            if total > MAX_NOTICE_CHARS:
                raise InputError(
                    "This PDF has too much text. Please upload the relevant pages."
                )
            if page_text:
                pages[f"notice:p{number}"] = page_text
    except (PyPdfError, OSError, KeyError, RecursionError) as error:
        raise InputError(
            "I could not read this PDF. Please try exporting it again."
        ) from error

    if not pages:
        raise InputError(
            "I could not find selectable text. Please upload a text-based PDF."
        )
    return pages
