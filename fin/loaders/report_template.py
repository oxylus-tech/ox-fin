from __future__ import annotations
from decimal import Decimal
from typing import Generator


from ..models import ReportSectionTemplate, ReportTemplate
from ..schemas.loaders import ReportSectionSchema, ReportTemplateSchema
from .base import BaseLoader, ModelItemsMap


__all__ = ("ReportTemplateLoader",)


class ReportTemplateLoader(BaseLoader):
    """Handle import of a report template schema."""

    schema_class = ReportTemplateSchema

    def run(self, *args, save=False, **kwargs) -> ModelItemsMap:
        """
        Run import and ensure section previous are resolved.
        """
        results = super().run(*args, save=save, **kwargs)

        # resolution is done in save, so when not saving we need to handle it here.
        if items := (not save and results["sections"]):
            self.resolve_previous(items)

        return results

    def get_items(self, schema: ReportTemplateSchema, template_id=None, **kwargs) -> ModelItemsMap:
        """Return template and sections for the provided schema.

        The returned dictionary contains:

        - ``template``: the template instance.
        - ``sections``: the root of the template sections (previous not resolved here).
        - ``all_sections``: all sections, including nested ones.
        """
        template = ReportTemplate(
            pk=template_id,
            name=schema.name,
            title=schema.title,
            description=schema.description,
        )

        sections = self.get_sections(schema.sections, template)
        return {
            "template": template,
            "sections": sections,
        }

    def get_sections(
        self, section_schemas: list[ReportSectionSchema], template, parent=None
    ) -> list[ReportSectionTemplate]:
        """
        Return Section instances for the provided list of section schemas.

        The result is a list of the root sections.

        The sections with children have an attribute ``_sections`` set to it.
        The sections can have a ``_previous`` attribute with the value of
        :py:attr:`fin.schemas.loaders.ReportSectionSchema.previous`.

        :param section_schemas: the list of ReportSectionSchema.
        :param template: the ReportTemplate used as section's init argument.
        :param parent: the parent ReportSectionTemplate used as section's init argument.
        """
        items = []
        for idx, dat in enumerate(section_schemas):
            if isinstance(dat, str):
                pass

            section = ReportSectionTemplate(
                template=template,
                parent=parent,
                order=idx,
                name=dat.name,
                code=str(dat.code) if dat.code is not None else None,
                weight=dat.weight and Decimal(dat.weight) or Decimal("1"),
                formula=dat.formula,
                annexe=dat.annexe,
            )

            if dat.previous:
                section._previous = dat.previous

            items.append(section)

            if sections := dat.sections:
                section._sections = self.get_sections(sections, template, section)
        return items

    def save(self, template: ReportTemplate, sections: list[ReportSectionTemplate]):
        """Save template and sections."""
        # The algorithm ensure:
        # - BFS tree traversal of nested sections (non-recursive)
        # - BFS to ensure parental
        # - the todo list holds a list of ``(sections, in_db_sections)``
        # - ``in_db_sections`` is a dict of section's ``{code: id}``
        # - we ensure to update existing, and create new ones
        # - sections are handled by blocks of the same parent. We could have decided to
        #   go to a more optimal way (by BFS level) but we need to take in account
        #   that there may be conflicting code (twice the same code, different parent, same BFS level).

        if template.pk:
            in_db = template.sections.filter(parent__isnull=True)
        else:
            in_db = None

        template.save()

        todo = [(sections, in_db)]
        to_update = []
        while todo:
            # We assume non-cyclic tree
            items, query = todo.pop(0)
            to_create, to_update_ = self.create_or_update(ReportSectionTemplate, items, query, "code", save=False)

            for item in items:
                if children := getattr(item, "_sections", None):
                    todo.append((children, ReportSectionTemplate.objects.filter(parent=item) if item.pk else None))

            ReportSectionTemplate.objects.bulk_create(to_create)
            to_update.extend(to_update_)

        if to_update:
            ReportSectionTemplate.objects.bulk_update(
                to_update, ["order", "name", "weight", "formula", "annexe"], batch_size=100
            )

        # we resolve after because to avoid complex dependency saving order resolution
        to_update = list(self.resolve_previous(sections))
        if to_update:
            ReportSectionTemplate.objects.bulk_update(to_update, ["previous"])

    def resolve_previous(self, sections: list[ReportSectionTemplate]) -> Generator[ReportSectionTemplate, None]:
        """
        Resolve and set ``previous`` on sections when applicable.

        Yield all sections targeting a previous section.
        """
        sections = list(self.iter_dfs(sections))
        by_id = {s.code: s for s in sections}
        for section in sections:
            if code := getattr(section, "_previous", None):
                try:
                    section.previous = by_id[code]
                    yield section
                except KeyError:
                    raise KeyError(f"Previous section '{code}' not found code for section {section.code}.")

    def iter_dfs(self, sections) -> Generator[ReportSectionTemplate, None]:
        """Iter over all sections and children DFS"""
        for section in sections:
            yield section

            if children := getattr(section, "_sections", None):
                yield from self.iter_dfs(children)

    def clear(self, template, **_):
        if template.pk:
            template.sections.all().delete()
