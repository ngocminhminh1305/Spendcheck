"""Request and response bodies of the public /api routes used by the website."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500, examples=["chagee 4.25 yesterday"])


class Draft(BaseModel):
    """A typed entry turned into a transaction the user confirms (or edits) before saving."""

    text: str
    amount: float | None
    merchant: str | None
    date: date
    category: str | None
    category_source: Literal["lookup", "model"] | None = None   # Module 2: catalogue or ML guess
    category_confidence: float | None = None                     # ML probability; None for lookups
    missing_fields: list[str] = Field(default_factory=list)      # what the user still has to fill in
    needs_review: bool = False         # missing fields, or a low-confidence category guess
    notes: list[str] = Field(default_factory=list)               # plain-English explanations for the UI


class TransactionIn(BaseModel):
    date: date
    amount: float = Field(gt=0, le=100_000)
    merchant: str = Field(min_length=1, max_length=120)
    category: str
    raw_text: str | None = Field(default=None, max_length=500)
    category_confidence: float | None = Field(default=None, ge=0, le=1)


class Transaction(TransactionIn):
    txn_id: int


class CategoryTotal(BaseModel):
    category: str
    amount: float
    budget: float | None = None


class DayTotal(BaseModel):
    date: date
    amount: float


class Summary(BaseModel):
    month: str                         # YYYY-MM
    spent: float
    budget: float | None               # overall budget for the month
    transactions: int
    by_category: list[CategoryTotal]
    by_day: list[DayTotal]


class BudgetIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    category: str | None = None        # None = overall monthly budget
    amount: float = Field(gt=0, le=1_000_000)


class Budget(BudgetIn):
    pass


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    # {"name", "tone"} from the personalisation panel; Module 4 validates it.
    persona: dict[str, Any] | None = None


class Status(BaseModel):
    gateway: bool
    database: bool
    modules: dict[str, bool]
    demo_user: str
    today: date


JSON = dict[str, Any]
