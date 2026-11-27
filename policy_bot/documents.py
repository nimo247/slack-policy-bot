from io import BytesIO

from docx import Document


def answer_docx(question: str, reply: str) -> bytes:
    document = Document()
    document.add_heading("Academic Policy Answer", level=0)
    document.add_heading("Question", level=1)
    document.add_paragraph(question)

    answer, separator, sources = reply.rpartition("\n\nSources\n")
    document.add_heading("Answer", level=1)
    document.add_paragraph(answer if separator else reply)
    if separator:
        document.add_heading("Sources", level=1)
        for source in sources.split("\n\n"):
            document.add_paragraph(source)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
