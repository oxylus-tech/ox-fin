from __future__ import annotations
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class XBRLFact(BaseModel):
    """An XBRL fact."""

    concept: str
    value: Decimal | None = None
    unit: str = ("EUR",)
    period: str = "instant"
    decimals: int = 0
    dimensions: dict[str, str] = Field(default_factory=dict)


class XBRLContext(BaseModel):
    """An XBRL context."""

    id: str
    entity: str
    period: date
    dimensions: dict[str, str]


class XBRLUnit(BaseModel):
    """An XBRL unit."""

    id: str
    measure: str


class XBRLInstance(BaseModel):
    """The whole XBRL document."""

    schema_ref: str
    contexts: list[XBRLContext]
    units: list[XBRLUnit]
    facts: list[XBRLFact]
