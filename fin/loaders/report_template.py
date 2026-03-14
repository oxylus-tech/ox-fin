from __future__ import annotations
from decimal import Decimal


from ..models import ReportSection, ReportTemplate
from ..schemas.loaders import ReportSectionSchema, ReportTemplateSchema
from .base import BaseLoader, ModelItemsMap


__all__ = ("ReportTemplateLoader",)


class ReportTemplateLoader(BaseLoader):
    """Handle import of a report template schema."""

    schema_class = ReportTemplateSchema

    def get_items(self, schema: ReportTemplateSchema, template_id=None, **kwargs) -> ModelItemsMap:
        """Return template and sections for the provided schema.

        The returned dictionary contains:

        - ``template``: the template instance.
        - ``sections``: the root of the template sections.
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

    def get_sections(self, section_schemas: list[ReportSectionSchema], template, parent=None) -> list[ReportSection]:
        """
        Return Section instances for the provided list of section schemas.

        The result is a list of the root sections.
        The sections with children have an attribute ``_sections`` set to it.

        :param section_schemas: the list of ReportSectionSchema.
        :param template: the ReportTemplate used as section's init argument.
        :param parent: the parent ReportSectionTemplate used as section's init argument.
        """
        items = []
        for idx, dat in enumerate(section_schemas):
            if isinstance(dat, str):
                pass

            section = ReportSection(
                template=template,
                parent=parent,
                order=idx,
                name=dat.name,
                code=str(dat.code) if dat.code is not None else None,
                weight=dat.weight and Decimal(dat.weight) or Decimal("1"),
                formula=dat.formula,
                annexe=dat.annexe,
            )
            items.append(section)
            if sections := dat.sections:
                section._sections = self.get_sections(sections, template, section)
        return items

    def save(self, template: ReportTemplate, sections: list[ReportSection]):
        """Save template and sections."""
        # The algorithm ensure:
        # - BFS tree traversal of nested sections (non-recursive)
        # - BFS to ensure parental
        # - the todo list holds a list of ``(sections, in_db_sections)``
        # - ``in_db_sections`` is a dict of section's ``{code: id}``
        # - we ensure to update existing, and create new ones

        if template.pk:
            in_db = template.sections.filter(parent__isnull=True)
        else:
            in_db = None

        template.save()

        todo = [(sections, in_db)]
        to_update = []
        while todo:
            # We assume non-cyclic tree
            sections, query = todo.pop(0)
            to_create, to_update_ = self.create_or_update(ReportSection, sections, query, "code", save=False)

            for section in sections:
                if children := getattr(section, "_sections", None):
                    todo.append((children, ReportSection.objects.filter(parent=section) if section.pk else None))

            ReportSection.objects.bulk_create(to_create)
            to_update.extend(to_update_)

        ReportSection.objects.bulk_update(sections, ["order", "name", "weight", "formula", "annexe"], batch_size=100)

    def clear(self, template, **_):
        if template.pk:
            template.sections.all().delete()
