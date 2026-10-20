"""Generate a small fake annual report PDF with known facts on known pages.

Used by the unit tests and for an end-to-end check before real reports are downloaded:

    docker compose run --rm reader-eval python eval/make_sample_report.py /data/reports/sample
    docker compose run --rm reader-eval python -m ingest.run --manifest /data/reports/sample/manifest.csv

Known facts (page = PDF page):
    p2  net profit S$1.23 billion, up 12%; final dividend 54 cents per share
    p3  financial highlights table: revenue 4,560.1 / net profit 1,234.5 (S$ million)
    p4  4,321 employees across 6 markets (on a long page that must be split into chunks)
    p5  key risks: credit risk, interest rate risk and cyber risk
"""

import csv
import sys
from pathlib import Path

import pymupdf

COMPANY, TICKER, YEAR, DOC_ID = "Demo Holdings Ltd", "DMO", 2025, "sample/DMO/2025"
WIDTH, HEIGHT = 595, 842   # A4 in points

PAGES = {
    1: ["Annual Report 2025", "Building a resilient future for our customers, staff and shareholders."],
    2: ["Chairman's statement",
        "In 2025, Demo Holdings achieved a record net profit of S$1.23 billion, up 12% from 2024, "
        "driven by higher net interest income and strong growth in fee income.",
        "The Board proposes a final dividend of 54 cents per share, bringing the total for the year "
        "to 102 cents."],
    3: ["Financial highlights (S$ million)"],
    4: ["Sustainability and our people"]
       + [f"Paragraph {i}: our sustainability programme continued to expand this year, covering "
          f"energy efficiency in branches, community volunteering and responsible financing across "
          f"the region, with targets reviewed by the Board every quarter." for i in range(1, 7)]
       + ["As at 31 December 2025, the Group employed 4,321 people across 6 markets."],
    5: ["Risk management",
        "Key risks include credit risk, interest rate risk and cyber risk. The Board Risk Committee "
        "reviews each of them at least twice a year."],
}
TABLE = [["", "2025", "2024"], ["Revenue", "4,560.1", "4,100.7"], ["Net profit", "1,234.5", "1,100.2"],
         ["Dividend per share (cents)", "102", "90"]]


def _draw_table(page: pymupdf.Page, top: float) -> None:
    """A ruled table, the way financial highlights are usually printed."""
    xs, row_h = [50, 300, 420, 545], 24
    for r, row in enumerate(TABLE):
        y = top + r * row_h
        for c, cell in enumerate(row):
            page.insert_text((xs[c] + 6, y + 16), cell, fontsize=10)
    for r in range(len(TABLE) + 1):
        page.draw_line((xs[0], top + r * row_h), (xs[-1], top + r * row_h))
    for x in xs:
        page.draw_line((x, top), (x, top + len(TABLE) * row_h))


def make_sample_report(pdf_path: Path) -> None:
    doc = pymupdf.open()
    for number, paragraphs in PAGES.items():
        page = doc.new_page(width=WIDTH, height=HEIGHT)
        page.insert_text((50, 30), COMPANY, fontsize=8)                                     # running header
        page.insert_text((50, HEIGHT - 20), f"{COMPANY} Annual Report 2025 | {number}", fontsize=8)   # footer
        y = 70
        for text in paragraphs:   # separate text boxes become separate paragraphs (PDF blocks)
            rect = pymupdf.Rect(50, y, WIDTH - 50, y + 90)
            spare = page.insert_textbox(rect, text, fontsize=10)
            y += 90 - spare + 14
        if number == 3:
            _draw_table(page, top=y + 10)
    doc.save(pdf_path)
    doc.close()


def main(folder: str) -> None:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    make_sample_report(out / "demo_holdings_2025.pdf")
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["doc_id", "corpus", "company", "ticker", "fiscal_year", "path"])
        writer.writerow([DOC_ID, "sgx", COMPANY, TICKER, YEAR, "demo_holdings_2025.pdf"])
    print(f"wrote {out / 'demo_holdings_2025.pdf'} and {out / 'manifest.csv'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/data/reports/sample")
