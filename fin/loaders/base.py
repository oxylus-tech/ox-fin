from abc import ABC, abstractmethod
from typing import Type, Iterable

from django.db import models
from pydantic import BaseModel

from ..schemas.loaders import BaseSchema
from ..utils import yaml


__all__ = ("ModelItemsMap", "BaseSchema", "BaseLoader")


ModelItemsMap = dict[str, list[models.Model]]


class BaseLoader(ABC):
    """Base class used to import a schema.

    .. note::
        Validation error are from pydantic.
    """

    schema_class: Type[BaseSchema] = BaseSchema

    def run(self, path, save=False, clear=False, **kwargs) -> ModelItemsMap:
        """Import schema."""
        schema = self.load(path)
        items = self.get_items(schema, **kwargs)

        if clear:
            self.clear(**items)

        if save:
            self.save(**items)

        return items

    @abstractmethod
    def get_items(self, schema: BaseSchema, **kwargs) -> ModelItemsMap:
        """Return django models based on the provided schema.

        It returns a map of arbitrary type names and list of django model
        instances.
        """
        pass

    @abstractmethod
    def save(self, **items: ModelItemsMap):
        """Save the items into the database."""
        pass

    def clear(self, items: ModelItemsMap):
        """Clear database from existing items."""
        pass

    def load(self, path) -> BaseModel:
        """Load a provided path."""
        data = yaml.load(path)
        return self.schema_class.validate(data)

    @staticmethod
    def create_or_update(
        model: Type[models.Model],
        items: list[models.Model],
        queryset: models.QuerySet | None,
        lookup: str,
        update_fields: Iterable[str] = None,
        save: bool = True,
    ) -> tuple[list[models.Model], list[models.Model]]:
        """
        Utility method to update or create items.

        :param model: model class
        :param items: items to save
        :param queryset: items queryset`
        :param lookup: field name to use as lookup.
        :param update_fields: fields to pass to ``bulk_update``.
        :param no_save: don't save, just return the result with mapped pk.
        :return a tuple of ``created, updated`` items.
        """
        if queryset is None:
            created, updated = items, []
        else:
            queryset = queryset.values_list(lookup, "id")
            in_db = {val: id for val, id in queryset}

            created, updated = [], []
            for item in items:
                key = getattr(item, lookup, None)
                item.pk = in_db.get(key)

                if item.pk:
                    updated.append(item)
                else:
                    created.append(item)

        if save:
            if not update_fields:
                raise ValueError("`update_fields` MUST be provided when saving.")
            model.objects.bulk_create(created)
            updated and model.objects.bulk_update(updated, update_fields, batch_size=100)
        return created, updated
