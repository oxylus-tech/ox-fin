from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


__all__ = ("Named", "LongNamed", "Described", "Titled")


class Named(models.Model):
    name = models.CharField(_("Name"), max_length=64)

    class Meta:
        abstract = True


class LongNamed(models.Model):
    name = models.CharField(_("Name"), max_length=256)

    class Meta:
        abstract = True


class Described(Named):
    description = models.TextField(_("Description"), default="", blank=True)

    class Meta:
        abstract = True


class Titled(models.Model):
    title = models.CharField(_("Title"), max_length=256, default="")

    class Meta:
        abstract = True
