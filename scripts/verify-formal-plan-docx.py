from pathlib import Path
import subprocess
import sys
import zipfile
from xml.etree import ElementTree

import pymupdf as fitz
from pypdf import PdfReader


EXPECTED = (
    "保全履歴の共有サービス",
    "工場の保全担当者が設備履歴をすぐ探せる事業",
    "どんな事業？",
    "現場ヒアリング",
    "採用: 小さく検証",
    "理由: 低リスク",
)
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx_text(source: Path) -> str:
    with zipfile.ZipFile(source) as package:
        required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml"}
        missing = required.difference(package.namelist())
        if missing:
            raise AssertionError(f"DOCX package is missing: {sorted(missing)}")
        document = ElementTree.fromstring(package.read("word/document.xml"))
    return "".join(node.text or "" for node in document.iter(f"{WORD_NAMESPACE}t"))


def main() -> None:
    source = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    extracted = extract_docx_text(source)
    for expected in EXPECTED:
        if expected not in extracted:
            raise AssertionError(f"missing exact Japanese DOCX text: {expected}")

    subprocess.run([
        "soffice", "--headless", "--convert-to", "pdf", "--outdir", str(output), str(source)
    ], check=True)
    pdf = output / f"{source.stem}.pdf"
    reader = PdfReader(pdf)
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for expected in EXPECTED:
        if expected not in pdf_text:
            raise AssertionError(f"missing exact Japanese converted-PDF text: {expected}")

    document = fitz.open(pdf)
    for index, page in enumerate(document):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pixmap.save(output / f"formal-plan-docx-{index + 1}.png")
        for block in page.get_text("blocks"):
            if block[2] > page.rect.width - 24:
                raise AssertionError(f"text overflows page {index + 1}: {block[2]} > {page.rect.width - 24}")


if __name__ == "__main__":
    main()
