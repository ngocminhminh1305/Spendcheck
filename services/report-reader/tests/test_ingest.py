"""Unit tests for PDF parsing and chunking, on a generated sample report (no database needed).

Run inside Docker:
    docker compose run --rm --no-deps reader-eval python -m unittest discover -s tests -v
"""

import tempfile
import unittest
from pathlib import Path

from eval.make_sample_report import COMPANY, make_sample_report
from ingest.chunking import _split_long, _split_table, chunk_pages
from ingest.pdf_parse import parse_pdf


class ParseSampleReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name) / "sample.pdf"
        make_sample_report(path)
        cls.pages = parse_pdf(str(path))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_one_entry_per_page_numbered_from_1(self):
        self.assertEqual([p.page for p in self.pages], [1, 2, 3, 4, 5])

    def test_running_header_and_footer_removed(self):
        for p in self.pages:
            self.assertNotIn("Annual Report 2025 |", p.text, f"footer left on page {p.page}")
            self.assertFalse(p.text.startswith(COMPANY), f"header left on page {p.page}")

    def test_facts_stay_on_their_pages(self):
        self.assertIn("S$1.23 billion", self.pages[1].text)
        self.assertIn("4,321 people", self.pages[3].text)
        self.assertIn("cyber risk", self.pages[4].text)

    def test_table_detected_and_not_duplicated_in_text(self):
        tables = self.pages[2].tables
        self.assertEqual(len(tables), 1)
        self.assertIn("Net profit", tables[0])
        self.assertIn("1,234.5", tables[0])
        self.assertNotIn("1,234.5", self.pages[2].text)

    def test_chunks(self):
        chunks = chunk_pages(self.pages, "Demo Holdings Ltd", 2025, max_chars=500, overlap=100)
        for c in chunks:   # every chunk is labelled with its own page
            self.assertTrue(c.content.startswith(f"Demo Holdings Ltd FY2025, page {c.page}:\n"))
        self.assertEqual([c.page for c in chunks if c.chunk_type == "table"], [3])
        page4 = [c for c in chunks if c.page == 4]
        self.assertGreater(len(page4), 1, "long page should be split")
        self.assertTrue(all(len(c.content) < 500 + 120 for c in page4))
        self.assertTrue(any("4,321 people" in c.content for c in page4))


class SplitHelpers(unittest.TestCase):
    def test_long_paragraph_split_at_sentences(self):
        text = " ".join(f"Sentence number {i} is here." for i in range(60))
        pieces = _split_long(text, 200)
        self.assertTrue(all(len(p) <= 200 for p in pieces))
        self.assertEqual(" ".join(pieces), text)

    def test_long_table_split_keeps_header(self):
        rows = [f"| item {i} | {i * 10} |" for i in range(100)]
        md = "\n".join(["| Item | Amount |", "|---|---|", *rows])
        pieces = _split_table(md, 400)
        self.assertGreater(len(pieces), 1)
        for piece in pieces:
            self.assertTrue(piece.startswith("| Item | Amount |\n|---|---|"))
        self.assertEqual(sum(len(p.splitlines()) - 2 for p in pieces), 100)


if __name__ == "__main__":
    unittest.main()
