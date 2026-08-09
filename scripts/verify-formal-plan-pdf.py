from pathlib import Path
import sys

import pymupdf as fitz
from pypdf import PdfReader


def main() -> None:
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(source)
    extracted = "\n".join(page.extract_text() for page in reader.pages)
    for expected in ("保全履歴の共有サービス", "工場の保全担当者", "どんな事業？", "現場ヒアリング"):
        if expected not in extracted:
            raise AssertionError(f"missing exact Japanese text: {expected}")
    decision_title = "採用: 現場ヒアリングから始める"
    decision_reason = "理由: 低リスクで検証できるため"
    if not any(decision_title in page.extract_text() and decision_reason in page.extract_text() for page in reader.pages):
        raise AssertionError("decision title and reason must stay on the same page")

    document = fitz.open(source)
    for index, page in enumerate(document):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pixmap.save(output / f"formal-plan-{index + 1}.png")
        for block in page.get_text("blocks"):
            if block[2] > page.rect.width - 24:
                raise AssertionError(f"text overflows page {index + 1}: {block[2]} > {page.rect.width - 24}")
        blocks = page.get_text("blocks")
        if len(document) > 1 and index == len(document) - 1:
            used_vertical_ratio = (max(block[3] for block in blocks) - min(block[1] for block in blocks)) / page.rect.height
            if used_vertical_ratio < 0.35:
                raise AssertionError(f"last page is mostly empty: {used_vertical_ratio:.1%} vertical use")


if __name__ == "__main__":
    main()
