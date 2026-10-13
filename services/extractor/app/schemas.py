"""Request and response shapes for the extraction API."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


EntityName = Literal["amount", "merchant", "date"]


class ExtractRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "text": "spent $8.90 at Kopitiam yesterday",
        "reference_datetime": "2026-10-09T18:30:00+08:00",
    }]})

    text: str
    reference_datetime: datetime

    @field_validator("reference_datetime")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reference_datetime must include a timezone offset")
        return value


class ExtractResponse(BaseModel):
    amount: float | None
    merchant: str | None
    date: date | None
    status: Literal["ok", "incomplete"]
    missing_fields: list[EntityName]
