from __future__ import annotations
import json
from typing import Type, Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel


__all__ = ("Named", "LongNamed", "Described", "Titled")


class Named(models.Model):
    name = models.CharField(_("Name"), max_length=64)

    class Meta:
        abstract = True


class LongNamed(models.Model):
    name = models.CharField(_("Name"), max_length=256)

    class Meta:
        abstract = True


class Described(models.Model):
    description = models.TextField(_("Description"), default="", blank=True)

    class Meta:
        abstract = True


class Titled(models.Model):
    title = models.CharField(_("Title"), max_length=256, default="")

    class Meta:
        abstract = True


class PydanticJSONField(models.JSONField):
    """
    This field automatically serialize/deserializes a Pydantic model.

    Features:

       - Accepts dict or Pydantic model on assignment
       - Returns Pydantic model on access
       - Validates data using Pydantic

    Example usage:

    .. code-block:: python

        class MyModel(models.Model):
            data = PydanticJSONField(schema=MyPydanticModel)

    """

    # TODO: strict model type validation (ensure we're using the right schema)

    def __init__(self, *args, schema: Type[BaseModel], **kwargs):
        self.schema = schema
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        """Ensure schema class is provided."""
        *all, kwargs = super().deconstruct()
        kwargs["schema"] = self.schema
        return *all, kwargs

    def from_db_value(self, value: Any, expression, connection) -> BaseModel | None:
        """Convert DB value → Pydantic model"""
        return self.to_python(value)

    def to_python(self, value: Any) -> BaseModel | None:
        """Convert assigned value → Pydantic model"""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as err:
                raise ValidationError(f"Invalid JSON: {err}")

        if value is None or isinstance(value, self.schema):
            return value
        return self.schema.model_validate(value)

    def get_prep_value(self, value: Any) -> Any:
        """Convert Pydantic model → JSON (dict) for DB storage"""
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value
