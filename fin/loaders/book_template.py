from __future__ import annotations


from ..models import BookTemplate, Account, Journal
from .base import BaseLoader, ModelItemsMap
from ..schemas.loaders import BookTemplateSchema


__all__ = "BookTemplateLoader"


class BookTemplateLoader(BaseLoader):
    """Handle import of a book template schema."""

    schema_class = BookTemplateSchema

    def get_items(self, schema: BookTemplateSchema, template_id=None, **kwargs) -> ModelItemsMap:
        """
        Return book template, accounts and journals for the provided schema.

        The returned dictionary contains:

        - ``template``: the book template.
        - ``accounts``: the book template's accounts.
        - ``journals``: the book template's journals.
        """

        template = BookTemplate(pk=template_id, name=schema.name, title=schema.title, description=schema.description)

        return {
            "template": template,
            "journals": [Journal(template=template, name=s.name, code=s.code) for s in schema.journals],
            "accounts": [
                Account(template=template, name=s.name, code=s.code, type=s.type, short=s.short)
                for s in schema.accounts
            ],
        }

    def save(self, template: BookTemplate, accounts: list[Account], journals: list[Journal]):
        if template.pk:
            j_query = Journal.objects.filter(template_id=template.pk)
            a_query = Account.objects.filter(template_id=template.pk)
        else:
            j_query, a_query = None, None

        template.save()
        self.create_or_update(Journal, journals, j_query, "code", ("code", "name"))
        self.create_or_update(Account, accounts, a_query, "code", ("code", "name", "type", "short"))

    def clear(self, template, **_):
        if template.pk:
            template.journals.all().delete()
            template.accounts.all().delete()
