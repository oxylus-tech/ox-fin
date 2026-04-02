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
        accounts = []

        for s in schema.accounts:
            account = Account(
                template=template,
                name=s.name,
                code=s.code,
                type=s.type,
                short=s.short,
            )
            account._set_accounts = {k: v for k, v in vars(s).items() if k.endswith("_account") if v is not None}
            accounts.append(account)

        template._set_accounts = {k: v for k, v in vars(schema).items() if k.endswith("_account") if v is not None}
        template._set_journals = {k: v for k, v in vars(schema).items() if k.endswith("_journal") if v is not None}

        return {
            "template": template,
            "journals": [Journal(template=template, name=s.name, code=s.code) for s in schema.journals],
            "accounts": accounts,
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

        # force db fetch
        j_query = Journal.objects.filter(template_id=template.pk)
        a_query = Account.objects.filter(template_id=template.pk)

        accounts_in_db = {a.code: a for a in a_query}
        journals_in_db = {j.code: j for j in j_query}

        # set template account fields
        update_fields = []
        if template._set_accounts:
            self.assign_related(template, accounts_in_db, template._set_accounts)
            update_fields.extend(template._set_accounts.keys())

        if template._set_journals:
            self.assign_related(template, journals_in_db, template._set_journals)
            update_fields.extend(template._set_journals.keys())

        update_fields and template.save(update_fields=update_fields)

        # accounts related fields
        updated_accounts, update_fields = self.assign_many_related(accounts, accounts_in_db, lambda a: a._set_accounts)
        Account.objects.bulk_update(updated_accounts, update_fields)

    def clear(self, template, **_):
        if template.pk:
            template.journals.all().delete()
            template.accounts.all().delete()
