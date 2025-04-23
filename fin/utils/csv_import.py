import csv
from pathlib import Path
from typing import Any

from django.db.models import Model


class ModelCSVImport:
    model: type[Model]
    map: dict[str, str] = None

    def __init__(self, model: type[Model], kwargs: dict[str, Any] | None = None, map: dict[str, str] | None = None):
        self.model = model
        self.fields = [f.name for f in model._meta.get_fields()]
        self.kwargs = kwargs or {}
        self.map = self.map and dict(self.map) or {}
        if map:
            self.map.update(map)

    def run(self, path: Path):
        """Run import."""
        with open(path, newline="") as stream:
            reader = csv.DictReader(stream)
            objs = [self.get_object(row) for row in reader]
        return self.model.objects.bulk_create(objs)

    def get_object(self, row):
        """Map values from row and return a model instance."""
        kwargs = dict(self.kwargs)
        for key, value in row.items():
            if k := self.map.get(key):
                kwargs[k] = value
            elif key not in ("pk", "id") and key in self.fields:
                kwargs[key] = value
        return self.model(**kwargs)
