from django.apps import AppConfig

__all__ = ("OxFinConfig",)


class OxFinConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fin"
    label = "ox_fin"
