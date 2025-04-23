from django.contrib import admin
from django.contrib.admin import EmptyFieldListFilter

from . import models

# @admin.register(models.Contact)
# class Contact(admin.ModelAdmin):
#     list_display = ('pk', 'fullname', 'short', 'vat', 'email', 'phone')


@admin.register(models.BookTemplate)
class BookTemplate(admin.ModelAdmin):
    list_display = ('pk', 'name')


@admin.register(models.Account)
class Account(admin.ModelAdmin):
    list_display = ('pk', 'code', 'name', 'short', 'type', 'template', 'is_debit')
    list_filter = ('template', 'is_debit', 'short')
    search_fields = ('code', 'name', 'short')


@admin.register(models.Journal)
class Journal(admin.ModelAdmin):
    list_display = ('pk', 'code', 'name', 'template')
    list_filter = ('template',)


@admin.register(models.Book)
class Book(admin.ModelAdmin):
    list_display = ('pk', 'name', 'template', 'path')

class LineInline(admin.TabularInline):
    model = models.Line


@admin.register(models.Move)
class Move(admin.ModelAdmin):
    list_display = ('pk', 'journal', 'date', 'reference', 'label', 'book')
    list_filter = ('book', 'journal', 'date')
    inlines = [LineInline]


@admin.register(models.Line)
class Line(admin.ModelAdmin):
    list_display = ('pk', 'account', 'amount', 'debit', 'credit', 'move')
    list_filter = ('move__book', 'move__journal', 'account__short')

    def debit(self, obj):
        return obj.amount if obj.is_debit else ''

    def credit(self, obj):
        return obj.amount if obj.is_credit else ''

