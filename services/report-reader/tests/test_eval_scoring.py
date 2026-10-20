"""Unit tests for the Module 5 evaluation's scoring rules (eval/run_eval.py). No LLM or database."""

import json
import unittest

from eval.run_eval import number_match, numbers, score_row


def row(answer, gold_answer="$1577.00", gold_pages=(5,), cited=(), retrieved=()):
    return {"id": "q", "doc_id": "BOEING_2022_10K", "mode": "full", "answer": answer, "gold_answer": gold_answer,
            "gold_pages": json.dumps(list(gold_pages)), "cited": json.dumps([list(c) for c in cited]),
            "retrieved": json.dumps([list(r) for r in retrieved]), "grade": "", "grade_method": "", "error": ""}


class NumberMatching(unittest.TestCase):
    def test_numbers_ignore_years_and_commas(self):
        self.assertEqual(numbers("In FY2022 capex was $1,577.00 million, 24.4% of revenue."), [1577.0, 24.4])

    def test_short_numeric_gold_answers(self):
        self.assertTrue(number_match("$1577.00", "Capital expenditure was $1,577 million in FY2022."))
        self.assertTrue(number_match("24.4%", "The margin was about 24.39%."))          # within 1%
        self.assertFalse(number_match("$1577.00", "Capital expenditure was $1,800 million."))

    def test_long_or_non_numeric_gold_needs_the_judge(self):
        self.assertIsNone(number_match("Yes", "Yes, it is capital intensive."))
        self.assertIsNone(number_match("No. The company's quick ratio of 0.65 suggests weak liquidity.", "0.65"))


class RetrievalAndCitations(unittest.TestCase):
    def test_hits_and_citation_accuracy(self):
        r = row("Capex was $1,577 million [p. 5].", cited=[("BOEING_2022_10K", 5), ("BOEING_2022_10K", 9)],
                retrieved=[("AMD_2022_10K", 5), ("BOEING_2022_10K", 5)])
        score_row(r)
        self.assertEqual((r["doc_hit"], r["page_hit"]), (True, True))
        self.assertEqual((r["citations_total"], r["citations_correct"]), (2, 1))
        self.assertEqual((r["grade"], r["grade_method"]), ("correct", "number-match"))

    def test_right_page_number_in_the_wrong_report_does_not_count(self):
        r = row("Capex was $1,577 million.", cited=[("AMD_2022_10K", 5)], retrieved=[("AMD_2022_10K", 5)])
        score_row(r)
        self.assertEqual((r["doc_hit"], r["page_hit"], r["citations_correct"]), (False, False, 0))

    def test_existing_grades_are_kept(self):
        r = row("Capex was $1,800 million.")
        r["grade"], r["grade_method"] = "correct", "manual"
        score_row(r)
        self.assertEqual((r["grade"], r["grade_method"]), ("correct", "manual"))


if __name__ == "__main__":
    unittest.main()
