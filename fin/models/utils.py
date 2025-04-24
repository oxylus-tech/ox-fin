from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


__all__ = ("Named", "Described")


class Named(models.Model):
    name = models.CharField(_("Name"), max_length=64)

    class Meta:
        abstract = True


class Described(Named):
    description = models.TextField(_("Description"), default="", blank=True)

    class Meta:
        abstract = True
