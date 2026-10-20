"""Unit tests for scoping, rank fusion and citation handling, with a fake LLM (no database needed).

Run inside Docker:
    docker compose run --rm --no-deps reader-eval python -m unittest discover -s tests -v
"""

import unittest

from spendcheck_common.llm import LLM, LLMReply

from app.answer import NOTHING_FOUND, REFUSED, answer_question, parse_page_marks, passage, resolve_source_labels
from app.config import Settings
from app.glossary import expansion_terms
from app.retriever import reciprocal_rank_fusion, resolve_scope, whole_pages, year_in
from app.schemas import AskRequest, DocumentInfo
from app.store import ChunkHit

DOCS = [
    DocumentInfo(doc_id="sgx/D05/2025", corpus="sgx", company="DBS Group Holdings", ticker="D05", fiscal_year=2025, n_pages=200),
    DocumentInfo(doc_id="sgx/D05/2024", corpus="sgx", company="DBS Group Holdings", ticker="D05", fiscal_year=2024, n_pages=190),
    DocumentInfo(doc_id="sgx/C6L/2026", corpus="sgx", company="Singapore Airlines", ticker="C6L", fiscal_year=2026, n_pages=250),
    DocumentInfo(doc_id="3M_2018_10K", corpus="financebench", company="3M", ticker="MMM", fiscal_year=2018, n_pages=160),
]


def hit(chunk_id, page, text="some text", doc_id="sgx/D05/2025"):
    return ChunkHit(chunk_id=chunk_id, doc_id=doc_id, company="DBS Group Holdings", fiscal_year=2025, page=page,
                    chunk_type="text", content=f"DBS Group Holdings FY2025, page {page}:\n{text}", score=0.5)


def scope(question, **kw):
    return resolve_scope(AskRequest(question=question, **kw), DOCS)


class Scope(unittest.TestCase):
    def test_company_and_year(self):
        self.assertEqual(scope("What was DBS's net profit in 2025?"), ["sgx/D05/2025"])
        self.assertEqual(scope("dbs net profit FY24"), ["sgx/D05/2024"])

    def test_company_without_year_keeps_all_its_reports(self):
        self.assertEqual(sorted(scope("What dividend did DBS pay?")), ["sgx/D05/2024", "sgx/D05/2025"])

    def test_aliases_tickers_and_full_names(self):
        self.assertEqual(scope("How big is SIA's fleet?"), ["sgx/C6L/2026"])
        self.assertEqual(scope("How many passengers did Singapore Airlines carry?"), ["sgx/C6L/2026"])
        self.assertEqual(scope("What was 3M's capex in FY2018?"), ["3M_2018_10K"])

    def test_no_company_means_search_everything(self):
        self.assertIsNone(scope("What is the outlook for the Singapore economy?"))

    def test_explicit_filters_win(self):
        self.assertEqual(scope("anything", doc_id="sgx/D05/2024"), ["sgx/D05/2024"])
        self.assertEqual(scope("net profit", company="DBS Group Holdings", fiscal_year=2024), ["sgx/D05/2024"])

    def test_year_parsing(self):
        self.assertEqual(year_in("revenue in 2025"), 2025)
        self.assertEqual(year_in("fy25 revenue"), 2025)
        self.assertIsNone(year_in("latest revenue"))


class Expansion(unittest.TestCase):
    def test_analyst_terms_add_statement_words(self):
        self.assertIn("total current liabilities", expansion_terms("How healthy is 3M's quick ratio?"))
        self.assertIn("purchases of property plant and equipment", expansion_terms("Is 3M capital-intensive?"))
        self.assertIn("distribution per unit", expansion_terms("What was CICT's DPU in 2025?"))
        self.assertEqual(expansion_terms("Who is the chairman?"), "")


class WholePages(unittest.TestCase):
    def test_ranked_chunks_become_whole_pages(self):
        ranked = [hit(5, 12, "best part"), hit(9, 30, "other page"), hit(6, 12, "same page again")]
        page_chunks = [hit(4, 12, "table on page 12"), hit(5, 12, "best part"), hit(6, 12, "same page again"),
                       hit(9, 30, "other page")]
        pages = whole_pages(ranked, page_chunks, max_pages=5)
        self.assertEqual([(p.page, p.chunk_type) for p in pages], [(12, "page"), (30, "page")])
        self.assertEqual(passage(pages[0], limit=1000), "table on page 12\n\nbest part\n\nsame page again")
        self.assertTrue(pages[0].content.startswith("DBS Group Holdings FY2025, page 12:\n"))
        self.assertEqual(len(whole_pages(ranked, page_chunks, max_pages=1)), 1)


class Fusion(unittest.TestCase):
    def test_reciprocal_rank_fusion(self):
        dense = [hit(1, 1), hit(2, 2), hit(3, 3)]
        keyword = [hit(3, 3), hit(4, 4)]
        self.assertEqual([h.chunk_id for h in reciprocal_rank_fusion([dense, keyword], k=4)], [3, 1, 2, 4])
        self.assertEqual([h.chunk_id for h in reciprocal_rank_fusion([dense, keyword], k=2)], [3, 1])


class Citations(unittest.TestCase):
    chunks = [hit(10, 3, "Net profit 1,234.5"), hit(11, 2, "Record net profit of S$1.23 billion")]

    def test_source_labels_become_pages(self):
        text = "Net profit was S$1.23 billion [S2]. It rose 12% [S1, S2]. Made up [S9]."
        answer, citations = resolve_source_labels(text, self.chunks)
        self.assertEqual(answer, "Net profit was S$1.23 billion [p. 2]. It rose 12% [p. 2, 3]. Made up .")
        self.assertEqual([c.page for c in citations], [2, 3])           # order of first mention
        self.assertEqual(citations[0].quote, "Record net profit of S$1.23 billion")

    def test_typed_page_marks(self):
        citations = parse_page_marks("Profit S$1.23b [p. 2]; staff 4,321 [p. 7].", self.chunks)
        self.assertEqual([(c.page, bool(c.quote)) for c in citations], [(2, True), (7, False)])

    def test_full_width_brackets(self):   # some models write 【p. 2】 or 【S2】
        self.assertEqual([c.page for c in parse_page_marks("S$1.23 billion【p. 2】【p. 3】", self.chunks)], [2, 3])
        answer, citations = resolve_source_labels("S$1.23 billion【S2】", self.chunks)
        self.assertEqual((answer, [c.page for c in citations]), ("S$1.23 billion[p. 2]", [2]))

    def test_quote_is_the_sentence_supporting_the_answer(self):
        chunk = hit(20, 4, "Our programme covered energy efficiency across the region. "
                           "As at 31 December 2025, the Group employed 4,321 people across 6 markets.")
        _, citations = resolve_source_labels("Demo employed 4,321 people [S1].", [chunk])
        self.assertTrue(citations[0].quote.startswith("As at 31 December 2025"))

    def test_passage_strips_label_and_shortens(self):
        self.assertEqual(passage(hit(1, 5, "Hello")), "Hello")
        self.assertTrue(passage(hit(1, 5, "word " * 200), limit=50).endswith(" ..."))


class FakeLLM(LLM):
    provider, model = "fake", "fake-model"

    def __init__(self, text="", stop="end"):
        self.text, self.stop, self.calls = text, stop, []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return LLMReply(text=self.text, tool_calls=[], stop=self.stop, assistant_message={})


class Answer(unittest.TestCase):
    def ask(self, llm, chunks, mode="full"):
        return answer_question(AskRequest(question="DBS net profit 2025?", mode=mode), chunks, llm=llm, settings=Settings())

    def test_full_mode_prompt_and_citations(self):
        llm = FakeLLM("DBS made S$1.23 billion [S2].")
        out = self.ask(llm, Citations.chunks)
        prompt = llm.calls[0]["messages"][0]["content"]
        self.assertIn("[S1]\nNet profit 1,234.5", prompt)
        self.assertIn("source label", llm.calls[0]["system"])
        self.assertEqual(out.answer, "DBS made S$1.23 billion [p. 2].")
        self.assertEqual([c.page for c in out.citations], [2])
        self.assertEqual(len(out.retrieved), 2)

    def test_basic_mode_shows_pages_to_the_model(self):
        llm = FakeLLM("S$1.23 billion [p. 2].")
        out = self.ask(llm, Citations.chunks, mode="basic")
        self.assertIn("page 2 ---", llm.calls[0]["messages"][0]["content"])
        self.assertEqual([c.page for c in out.citations], [2])

    def test_nothing_retrieved_skips_the_llm(self):
        llm = FakeLLM()
        out = self.ask(llm, [])
        self.assertEqual(out.answer, NOTHING_FOUND)
        self.assertEqual(llm.calls, [])

    def test_refusal(self):
        self.assertEqual(self.ask(FakeLLM(stop="refusal"), Citations.chunks).answer, REFUSED)


if __name__ == "__main__":
    unittest.main()
