"""Request and response bodies for the chat agent API (the contract in docs/CONTRACTS.md)."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Persona(BaseModel):
    """How the assistant talks to this user: "a friend, not a bank". Chosen in the website's
    personalisation panel and sent with every message. It changes wording only, never numbers."""

    name: str | None = Field(default=None, examples=["Bo"])
    tone: Literal["chill", "hype"] = "chill"

    @field_validator("name")
    @classmethod
    def plain_name(cls, value: str | None) -> str | None:
        # The name is placed in the LLM's instructions, so accept only a short plain name
        # (letters, spaces, hyphens, apostrophes): no room to smuggle in instructions.
        if value is None or not value.strip():
            return None
        value = " ".join(value.split())
        if len(value) > 30 or not value[0].isalpha() or not all(c.isalpha() or c in " '-" for c in value):
            raise ValueError("name must be up to 30 letters (spaces, hyphens and apostrophes allowed)")
        return value


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000, examples=["Can I afford a $300 concert ticket?"])
    # Earlier turns of this conversation, oldest first. The service itself is stateless.
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    # "agent" = normal product behaviour. "baseline" = evaluation baseline from the proposal:
    # the same LLM answering from pasted transaction history, with no database tools.
    mode: Literal["agent", "baseline"] = "agent"
    # Optional voice settings. The evaluation sends none, so results use the neutral default.
    persona: Persona | None = None


class ToolStep(BaseModel):
    """One tool call the agent made. Returned so the UI can show how an answer was computed."""

    tool: str
    input: dict[str, Any]
    output_preview: str
    is_error: bool = False


class ReportCitation(BaseModel):
    """A page in an annual report that supports the answer (passed through from Module 5)."""

    doc_id: str
    company: str
    fiscal_year: int | None = None
    page: int
    quote: str


class ChatResponse(BaseModel):
    answer: str
    mode: Literal["agent", "baseline"]
    steps: list[ToolStep] = Field(default_factory=list)
    citations: list[ReportCitation] = Field(default_factory=list)
    model: str | None = None
