from django.contrib import admin

# from django.urls import reverse
# from django.utils.safestring import mark_safe

from . import models


@admin.register(models.BookTemplate)
class BookTemplateAdmin(admin.ModelAdmin):
    list_display = ("pk", "name")


@admin.register(models.Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("pk", "code", "name", "short", "type", "template", "is_debit")
    list_filter = ("template", "is_debit", "short")
    list_editable = (
        "short",
        "type",
    )
    search_fields = ("code", "name", "short")


@admin.register(models.Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ("pk", "code", "name", "template")
    list_filter = ("template",)


@admin.register(models.Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("pk", "title", "template", "path")


class LineInline(admin.TabularInline):
    model = models.Line
    fields = ("amount", "is_debit", "account")


@admin.register(models.Move)
class MoveAdmin(admin.ModelAdmin):
    list_display = ("pk", "journal", "date", "reference", "description", "book")
    list_filter = ("book", "journal", "date")
    inlines = [LineInline]


@admin.register(models.Line)
class LineAdmin(admin.ModelAdmin):
    list_display = ("pk", "move", "amount", "is_debit", "debit", "credit", "account")
    list_filter = ("move__book", "move__journal", "account__short")
    list_editable = (
        "amount",
        "is_debit",
        "account",
    )

    # def move_link(self, obj):
    #    return mark_safe('<a href="{}">{}</a>'.format(
    #        reverse("admin:ox_fin_move_change", args=(obj.move_id,)),
    #        obj.move
    #    ))
