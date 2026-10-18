"""Public request and response contract for the gateway."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal["Food & Drink", "Groceries", "Transport", "Shopping", "Entertainment",
                   "Bills & Utilities", "Health", "Education", "Other"]


class ClassifyRequest(BaseModel):
    """One extracted merchant, without amount, date or unrelated context."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"merchant": "NETS*KOPITIAM"}],
    })
    merchant: str = Field(min_length=1, max_length=500, strict=True)

    @field_validator("merchant")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        """Reject whitespace-only input while retaining the original descriptor."""
        if not value.strip():
            raise ValueError("merchant must not be blank")
        if not any(character.isalnum() for character in value):
            raise ValueError("merchant must contain letters or digits")
        return value


class ClassifyResponse(BaseModel):
    """Automatic category; lookup confidence is null, model probability uncalibrated."""

    category: Category
    confidence: float | None = Field(ge=0, le=1)
    source: Literal["lookup", "model"]
    model_version: str


class HealthResponse(BaseModel):
    """Model readiness and the provenance status of the loaded artifact."""

    status: Literal["ready"]
    model_version: str
    data_status: str
