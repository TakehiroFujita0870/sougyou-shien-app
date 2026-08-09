from pathlib import Path
import sys

import fitz
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

    document = fitz.open(source)
    for index, page in enumerate(document):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pixmap.save(output / f"formal-plan-{index + 1}.png")
        for block in page.get_text("blocks"):
            if block[2] > page.rect.width - 24:
                raise AssertionError(f"text overflows page {index + 1}: {block[2]} > {page.rect.width - 24}")


if __name__ == "__main__":
    main()
