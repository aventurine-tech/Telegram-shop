"""Build docs/run-and-test.pdf from docs/run-and-test.md.

    pip install reportlab
    python docs/build_pdf.py

Handles the small Markdown subset the guide uses: # / ## headings, paragraphs, "- " bullets, "1. " numbered
items and fenced code blocks.
"""
import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, Preformatted, SimpleDocTemplate, Spacer

HERE = Path(__file__).parent


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', text)


def build(src: Path, out: Path) -> None:
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=18, spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14)
    code = ParagraphStyle("code", parent=styles["Code"], fontSize=8.5, leading=11, leftIndent=8,
                          backColor="#f1f3f5", borderPadding=4)

    story, lines, i = [], src.read_text(encoding="utf-8").splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            story += [Preformatted("\n".join(block), code), Spacer(1, 4)]
        elif line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), h1))
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), h2))
        elif re.match(r"^(- |\d+\. )", line):
            ordered = line[0].isdigit()
            items = []
            while i < len(lines) and re.match(r"^(- |\d+\. )", lines[i]):
                items.append(ListItem(Paragraph(inline(re.sub(r"^(- |\d+\. )", "", lines[i])), body)))
                i += 1
            story.append(ListFlowable(items, bulletType="1" if ordered else "bullet", leftIndent=14))
            continue
        elif line.strip():
            story.append(Paragraph(inline(line), body))
        i += 1
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=16 * mm, title="Run and test the shop bot").build(story)


if __name__ == "__main__":
    build(HERE / "run-and-test.md", HERE / "run-and-test.pdf")
    print("wrote", HERE / "run-and-test.pdf")
    sys.exit(0)
