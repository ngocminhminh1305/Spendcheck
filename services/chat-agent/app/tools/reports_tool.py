"""search_annual_reports tool: hands company questions to Module 5 (SGX Report Reader).

This is what lets one chat answer both "how much did I spend on food?" (Module 4's own data)
and "how profitable is DBS?" (Module 5's annual reports) in the same conversation, the
"budgeting and investing in one assistant" idea from the proposal.

Endpoint contract (docs/CONTRACTS.md):  POST {REPORT_READER_URL}/v1/ask
"""

from typing import Any

import httpx

TOOL_DEFINITION = {
    "name": "search_annual_reports",
    "description": (
        "Answer a factual question about a Singapore-listed (SGX) company using its annual report. "
        "Returns an answer with page citations. Use it for any question about a company's "
        "financial results, business, risks or strategy. Put the company name and the year in "
        "the question. It gives facts only, never buy/sell advice."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "A self-contained question, e.g. \"What was DBS Group's net profit in 2024?\"",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    },
}


def search_annual_reports(report_reader_url: str, question: str, request_id: str | None = None) -> dict[str, Any]:
    """Ask Module 5. Returns its JSON: answer, citations, ... Raises httpx.HTTPError on failure."""
    headers = {"X-Request-ID": request_id} if request_id else {}
    response = httpx.post(
        f"{report_reader_url}/v1/ask",
        json={"question": question, "mode": "full"},
        headers=headers,
        timeout=90.0,   # Module 5 makes its own LLM call
    )
    response.raise_for_status()
    return response.json()
