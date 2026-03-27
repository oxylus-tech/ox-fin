from __future__ import annotations
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator

from ..models import Account
from .xbrl import XBRLFact, XBRLSchema


__all__ = (
    "BaseSchema",
    "JournalSchema",
    "AccountSchema",
    "BookTemplateSchema",
    "ReportSectionSchema",
    "ReportTemplateSchema",
)


class BaseSchema(BaseModel):
    """Base class for a schema."""

    name: str
    """ Name of the schema. """


# ---- Book Template
class JournalSchema(BaseModel):
    """An journal inside a book template schema."""

    name: str
    code: str


class AccountSchema(BaseModel):
    """An account inside a book template schema."""

    name: str
    code: str
    type: int | str | Account.Type
    short: str | None = None

    @field_validator("type", mode="after")
    @classmethod
    def validate_type(cls, value: int | str) -> Account.Type:
        if isinstance(value, str):
            return Account.Type.from_str(value)
        if isinstance(value, int):
            return Account.Type(value)
        return value


class BookTemplateSchema(BaseSchema):
    """Root object describing a book template."""

    journals: list[JournalSchema]
    accounts: list[AccountSchema]
    title: str = ""
    description: str = ""


# ---- Report template
class ReportSectionSchema(BaseModel):
    """A report section in the report template schema."""

    name: str
    code: Optional[str | int] = None
    weight: Decimal = Decimal("0")
    formula: Optional[str] = None
    annexe: Optional[str] = None
    sections: list[ReportSectionSchema] | None = None
    previous: Optional[str] = None
    xbrl: Optional[XBRLFact] = None


class ReportTemplateSchema(BaseSchema):
    """Root object describing a report template."""

    title: str
    description: str = ""
    sections: dict[str, ReportSectionSchema] | list[ReportSectionSchema]
    xbrl: Optional[XBRLSchema] = None
