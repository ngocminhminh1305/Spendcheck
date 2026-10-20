"""Finance glossary for query expansion (full mode only).

Investors ask in analyst language ("is it capital-intensive?", "quick ratio", "dragged down
growth"), but reports use statement language ("purchases of property, plant and equipment",
"total current assets", "organic sales"). Neither embeddings nor keyword search reliably bridge
that gap, so a matched concept adds the words the answer is likely to be printed with.
"""

import re

# (pattern in the question, words to add to the search)
GLOSSARY: list[tuple[str, str]] = [
    (r"capital[- ]intensive|capex|capital expenditure|fixed assets",
     "purchases of property plant and equipment capital expenditures property plant and equipment net total assets net sales"),
    (r"quick ratio|current ratio|liquidity|working capital|short[- ]term obligations",
     "balance sheet total current assets cash and cash equivalents marketable securities accounts receivable inventories total current liabilities"),
    (r"operating margin|operating income|operating profit|profitab",
     "operating income net sales cost of sales selling general and administrative expenses gross margin"),
    (r"gross margin|gross profit",
     "gross profit cost of sales net sales gross margin"),
    (r"free cash flow|cash flow|cash from operations",
     "statement of cash flows net cash provided by operating activities purchases of property plant and equipment"),
    (r"dividend|payout",
     "dividends paid cash dividends per share payout"),
    (r"segment|organic|dragged|growth|grew|decline",
     "sales change by business segment organic sales acquisitions divestitures translation total sales change"),
    (r"debt securities|registered|trading symbol|listed on|exchange",
     "securities registered pursuant to section 12(b) title of each class trading symbol name of each exchange notes due"),
    (r"return on assets|\broa\b",
     "net income total assets"),
    (r"return on equity|\broe\b",
     "net income total equity shareholders equity"),
    (r"inventory turnover|days inventory|inventor",
     "inventories cost of sales"),
    (r"effective tax|tax rate|income tax",
     "provision for income taxes income before income taxes effective tax rate"),
    (r"leverage|debt to|indebtedness|interest coverage|borrowings",
     "long-term debt short-term borrowings total debt interest expense"),
    (r"earnings per share|\beps\b",
     "earnings per share diluted basic net income"),
    (r"net profit|net income|net earnings|bottom line",
     "net income attributable profit for the year"),
    (r"revenue|turnover|top line|net sales",
     "net sales total revenues"),
    # SGX / Singapore report vocabulary
    (r"\bdpu\b|distribution per unit|distribution",
     "distribution per unit distributable income distributions to unitholders"),
    (r"\bnav\b|net asset value|book value",
     "net asset value per unit net asset value per share"),
    (r"net interest margin|\bnim\b",
     "net interest margin net interest income"),
    (r"gearing|aggregate leverage",
     "aggregate leverage gearing ratio total borrowings"),
    (r"occupancy",
     "committed occupancy portfolio occupancy"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), words) for p, words in GLOSSARY]


def expansion_terms(question: str) -> str:
    """Extra search words for the concepts found in the question ("" if none)."""
    return " ".join(words for pattern, words in _COMPILED if pattern.search(question))
