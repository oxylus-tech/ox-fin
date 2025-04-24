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
    search_fields = ("code", "name", "short")


@admin.register(models.Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ("pk", "code", "name", "template")
    list_filter = ("template",)


@admin.register(models.Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("pk", "name", "template", "path")


class LineInline(admin.TabularInline):
    model = models.Line


@admin.register(models.Move)
class MoveAdmin(admin.ModelAdmin):
    list_display = ("pk", "journal", "date", "reference", "label", "book")
    list_filter = ("book", "journal", "date")
    inlines = [LineInline]


@admin.register(models.Line)
class LineAdmin(admin.ModelAdmin):
    list_display = ("pk", "move", "amount", "debit", "credit", "account")
    list_filter = ("move__book", "move__journal", "account__short")
    list_editable = (
        "amount",
        "account",
    )

    # def move_link(self, obj):
    #    return mark_safe('<a href="{}">{}</a>'.format(
    #        reverse("admin:ox_fin_move_change", args=(obj.move_id,)),
    #        obj.move
    #    ))

    def debit(self, obj):
        return obj.amount if obj.is_debit else ""

    def credit(self, obj):
        return obj.amount if obj.is_credit else ""


class LineRuleInline(admin.TabularInline):
    model = models.LineRule


@admin.register(models.MoveRule)
class MoveRuleAdmin(admin.ModelAdmin):
    list_display = ("pk", "name", "code", "template", "journal")
    list_filter = ("template", "journal")
    search_fields = ("name", "code", "line_rule__code", "line_rule__name")
    inlines = [LineRuleInline]


@admin.register(models.LineRule)
class LineRuleAdmin(admin.ModelAdmin):
    list_display = ("pk", "name", "code", "move_rule", "account")
    list_filter = ("move_rule",)
    search_fields = (
        "name",
        "code",
        "move_rule__name",
    )
