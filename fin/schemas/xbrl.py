from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


__all__ = (
    "XBRLPeriod",
    "XBRLFact",
    "XBRLContext",
    "XBRLUnit",
    "XBRLEntity",
    "XBRLSchema",
    "XBRLInstance",
)


class XBRLPeriod(BaseModel):
    type: Literal["instant", "duration"] = "instant"
    instant: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    offset: int = 0


class XBRLFact(BaseModel):
    """An XBRL fact."""

    concept: str
    context_id: str
    """ Reference to a XBRL context, set by context resolver. """
    value: Optional[Decimal] = None
    unit: str = "EUR"
    decimals: int = 0
    dimensions: dict[str, str] = Field(default_factory=dict)
    """ Context dimensions """
    period: Optional[XBRLPeriod] = None
    """ Period the fact is related to (0=current, -1=previous). """


class XBRLContext(BaseModel):
    """An XBRL context."""

    id: str
    period: XBRLPeriod
    entity: str = None
    dimensions: dict[str, str] = Field(default_factory=dict)


class XBRLUnit(BaseModel):
    """An XBRL unit."""

    id: str
    measure: str


class XBRLEntity(BaseModel):
    """An XBRL entity."""

    scheme: str
    entity: str


class XBRLSchemaRef(BaseModel):
    """An XBRL schemaRef."""

    href: str
    type: str = "simple"
    arcrole: str = "http://www.w3.org/1999/xlink/properties/linkbase"


class XBRLSchema(BaseModel):
    """An XBRL document schema."""

    schema_ref: XBRLSchemaRef
    namespaces: dict[str, str] = Field(default_factory=dict)
    entity_scheme: str
    units: list[XBRLUnit]
    contexts: list[XBRLContext]


class XBRLInstance(XBRLSchema):
    """The whole XBRL document."""

    facts: list[XBRLFact]
