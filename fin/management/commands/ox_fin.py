from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

import pandas as pd
from rich import print, table, align

from fin import models
from fin.utils.report_builder import ReportBuilder
from fin.utils import import_template


def as_date(val):
    year, month, day = val.split("/")
    return date(int(year), int(month.lstrip("0")), int(day.lstrip("0")))


def decimal(val):
    # val = val.replace('.', '').replace(',', '.')
    if not val:
        return None
    return round(Decimal(val), 2)


class Command(BaseCommand):
    help = "Ledger book import for home's data."

    columns = {
        "date": as_date,
        "account": str,
        "label": str,
        "debit": decimal,
        "credit": decimal,
        "": None,
        "contact": None,
        "reference": str,
    }

    verbosity = 0
    debug = False

    book = None
    journals: dict[str, models.Journal] = None
    accounts: dict[str, models.Account] = None
    accounts_qs = None

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers()

        parser.add_argument("--book", "-b", type=int, help="Select the book (by id)")
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--debug", action="store_true")

        # --- main actions
        group = subparsers.add_parser("accounts")
        group.set_defaults(func=self.handle_accounts)

        group = subparsers.add_parser("annual-report")
        group.set_defaults(func=self.handle_annual_report)
        group.add_argument("--template", "-t", type=int, required=True, help="Report template ID")
        group.add_argument("--year", "-y", type=int, help="Filter by year")

        group = subparsers.add_parser("summary")
        group.set_defaults(func=self.handle_summary)
        group.add_argument("--year", "-y", type=int, help="Filter by year")

        # --- imports
        group = subparsers.add_parser("import")
        group.set_defaults(func=self.handle_import)
        group.add_argument("path", metavar="PATH", type=Path, action="append", help="Document path")
        # group.add_argument("--months", action="store_true", help="Print per month accounts summary")
        # group.add_argument("--details", "-d", action="store_true", help="Detailed summary (lines)")
        group.add_argument("--year", "-y", type=int, help="Filter by year")
        group.add_argument("--save", "-s", action="store_true", help="Save data in db")
        group.add_argument(
            "--clear",
            "-c",
            action="store_true",
            help="Delete all book data before import. When year is selected, only the transactions of this year will be removed.",
        )

        group = subparsers.add_parser("import-template", help="Import a book template from a YAML file.")
        group.set_defaults(func=self.handle_import_template)
        group.add_argument("path", metavar="PATH", type=Path, help="Book template YAML file")
        group.add_argument(
            "--template", "-t", type=int, help="Book template ID to update (instead of creating a new one."
        )
        group.add_argument("--save", "-s", action="store_true", help="Save data in db")
        group.add_argument(
            "--clear", "-c", action="store_true", help="Trunk accounts and journals not present in the YAML."
        )

        group = subparsers.add_parser("import-report", help="Import a report template from a YAML file.")
        group.set_defaults(func=self.handle_import_report)
        group.add_argument("path", metavar="PATH", type=Path, help="Report template YAML file")
        group.add_argument(
            "--template", "-t", type=int, help="Report template ID to update (instead of creating a new one."
        )
        group.add_argument("--save", "-s", action="store_true", help="Save data in db")
        group.add_argument(
            "--clear",
            "-c",
            action="store_true",
            help="Delete all report template data before import. \033[33mWARNING: this will drop all generated reports\033[0m",
        )

    def print(self, level, *args, **kwargs):
        if level <= self.verbosity:
            print(*args, **kwargs)

    @transaction.atomic
    def handle(self, book, func, verbose=0, debug=False, **kwargs):
        self.verbosity = verbose and 1 or 0
        self.debug = debug
        self.setup(book)
        return func(**kwargs)

    def setup(self, book):
        if book:
            self.book = models.Book.objects.get(pk=book)

            journals = models.Journal.objects.filter(template_id=self.book.template_id)
            self.journals = {journal.code: journal for journal in journals}

            self.accounts_qs = models.Account.objects.filter(template_id=self.book.template_id).order_by("code")
            self.accounts = {account.code: account for account in self.accounts_qs}
            self.accounts.update(
                {
                    account.code.ljust(6, "0"): account
                    for account in self.accounts_qs
                    if len(account.code) < 6 and account.code not in self.accounts
                }
            )

    def get_account(self, code, parent=True):
        """Get account by code, defaulting to parent if True."""
        while code:
            if account := self.accounts.get(code):
                return account
            elif not parent:
                break
            code = code[:-1]

    def group_lines(self, lines):
        # not the most efficient, but avoids to have to save to db
        # to display stuffs.
        for account in self.accounts_qs:
            yield account, [line for line in lines if line.account == account]

    def get_lines(self, year=None):
        lines = (
            models.Line.objects.filter(move__book=self.book)
            .select_related("move")
            .order_by("move__date", "move__reference", "-is_debit")
        )
        if year:
            lines = lines.filter(move__date__year=year)
        return lines

    # ---- Accounts
    def handle_accounts(self, **kwargs):
        t = table.Table(title=self.book.template.name)

        t.add_column("Account", style="cyan")
        t.add_column("Name")
        t.add_column("Type")
        t.add_column("")

        for account in self.accounts_qs.order_by("code"):
            ty = "debit" if account.is_debit else "credit"
            ty_2 = str(account.Type(account.type).label)
            match len(account.code):
                case 1:
                    t.add_section()
                    t.add_section()
                    t.add_row(account.code, align.Align(f"[bold ]{account.name}[/ bold]", "center"), ty, ty_2)
                    t.add_section()
                case 2:
                    t.add_section()
                    t.add_row(account.code, f"[bold yellow]{account.name}[/bold yellow]", ty, ty_2)
                case _:
                    pad = (len(account.code) - 2) * 2 * " "
                    t.add_row(pad + account.code, pad + account.name, ty, ty_2)
        print("\n", t)

    # ---- summary
    def handle_summary(self, year=None, **kwargs):
        lines = self.get_lines(year=year)
        self.summary(lines, self.book.name, details=True)

    def summary(self, lines, title=None, details=False):
        t = table.Table(title=title)

        t.add_column("Account", style="cyan")
        t.add_column("Name")
        t.add_column("Debit")
        t.add_column("Credit")
        t.add_column("Balance", style="cyan")

        for account, ls in self.group_lines(lines):
            if not ls:
                continue
            w = account.is_debit and 1 or -1
            debit = sum(line.debit for line in ls)
            credit = sum(line.credit for line in ls)

            if account.is_debit:
                debit_s = f"[yellow]{debit}[/yellow]"
                credit_s = str(credit)
            else:
                debit_s = str(debit)
                credit_s = f"[yellow]{credit}[/yellow]"

            details and t.add_section()
            t.add_row(account.code, account.name, debit_s, credit_s, str((debit - credit) * w))

            if details:
                balance = 0
                colors = ("green", "red")
                for line in ls:
                    balance += (line.debit - line.credit) * w
                    color = colors[int(balance < 0)] if balance != 0 else "white"
                    t.add_row(
                        "",
                        f"[i][yellow]{line.move.date}[/yellow] [magenta]{line.move.journal.code.ljust(3)}[/magenta] {line.move.label}[/i]",
                        str(line.debit),
                        str(line.credit),
                        f"[{color}]{balance}[/{color}]",
                    )

        print(t)

    def monthly_summary(self, lines, **kw):
        min_date, max_date = min(line.move.date for line in lines), max(line.move.date for line in lines)
        offset = min_date.replace(day=1)

        while offset <= max_date:
            offset_2 = (offset + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            lines_ = [line for line in lines if offset <= line.move.date <= offset_2]
            self.summary(lines_, f"{offset.year} - {offset.month}", **kw)
            offset = offset_2 + timedelta(days=1)

    # ---- Annual Report
    def handle_annual_report(self, template, year=None, **kwargs):
        template = models.ReportTemplate.objects.get(pk=template)
        lines = self.get_lines(year=year)

        builder = ReportBuilder(template, self.book)
        report, results = builder.create(lines, year)
        sections = template.sections.filter(parent__isnull=True).order_by("order")
        self.print_report(template, sections, results)

    _report_tags = {
        0: "b",
        1: "b yellow",
        2: "b",
        4: "i",
    }

    def print_report(self, template, sections, results=None):
        t = table.Table(title=template.label)
        t.add_column("Label")
        t.add_column("Code", style="cyan")
        if results:
            t.add_column("Value", style="cyan")
        else:
            t.add_column("Formula", style="italic")
        self.print_report_sections(t, sections, results=results)
        print(t)

    def print_report_sections(self, t, sections, depth=0, results=None):
        for section in sections:
            if tag := self._report_tags.get(depth):
                label = f"[{tag}]{section.label}[/{tag}]"
            else:
                label = section.label

            args = [
                (depth * 2 - 2) * " " + label,
                section.code or "",
            ]
            if results:
                if result := results.get(section.id):
                    result = str(round(result.value, 2))
                else:
                    result = ""
                args.append(result)
            else:
                args.append(section.formula or f"{section.weight or ''}")

            if depth == 0:
                t.add_section()
            t.add_row(*args)
            if depth == 0:
                t.add_section()

            children = (
                getattr(section, "_sections", None) or section.pk and section.children.all().order_by("order") or None
            )
            if children:
                self.print_report_sections(t, children, depth + 1, results=results)

    # ---- Import
    def handle_import(self, path, year=None, save=False, clear=False, **kwargs):
        moves, lines = [], []
        for p in path:
            m, li = self.read_file(p)
            moves.extend(m)
            lines.extend(li)

        moves.sort(key=lambda m: (m.date, m.reference or ""))
        lines.sort(key=lambda li: (li.move.date, li.move.reference or "", not li.is_debit))

        if year:
            moves = [m for m in moves if m.date.year == year]
            lines = [line for line in lines if line.move.date.year == year]

        if save:
            self.save(moves, lines, clear=clear, year=year)

        self.summary(lines, details=True)

    def save(self, moves, lines, clear=False, year=None):
        if clear:
            query = models.Move.objects.filter(book=self.book)
            if year:
                query = query.filter(date__year=year)
            query.delete()

        models.Move.objects.bulk_create(moves)
        models.Line.objects.bulk_create(lines)
        self.print(0, f"{len(moves)} moves and {len(lines)} lines saved")

    def read_file(self, path) -> tuple[list[models.Move], list[models.Line]]:
        """Read provided file and return moves and lines."""
        dfs = pd.read_excel(path, header=None, sheet_name=None, dtype=str)
        moves, lines = [], []
        for sheet_name, sheet in dfs.items():
            if journal := self.journals.get(sheet_name):
                move, line = self.read_journal(journal, sheet)
                moves.extend(move)
                lines.extend(line)

        self.print(0, f"[magenta]{path.name}[/magenta]: [b]{len(moves)} moves and {len(lines)} lines imported[/b]\n")
        return moves, lines

    def read_journal(self, journal, df):
        move_values = []
        moves, lines = [], []
        for row in df.iloc[1:].itertuples(index=False, name=None):
            values = self.get_values(row)
            if not values:
                continue

            if values.get("date") and move_values:
                move, line = self.create_move(journal, move_values)
                moves.append(move)
                lines.extend(line)
                move_values = []
            move_values.append(values)

        move, line = self.create_move(journal, move_values)
        moves.append(move)
        lines.extend(line)

        return moves, lines

    def get_values(self, row):
        if len(row) < len(self.columns):
            return

        values = {col: row[idx] for idx, col in enumerate(self.columns.keys()) if col}
        for key, ty in self.columns.items():
            if ty is not None:
                value = values.get(key)
                if value and pd.notna(value):
                    values[key] = ty(value)
                    continue
            values[key] = None

        return values

    def create_move(self, journal, move_values):
        values = move_values[0]
        move = models.Move(
            book=self.book, journal=journal, date=values["date"], reference=values["reference"], label=values["label"]
        )

        self.print(0, f"[green]{journal.code}[/green] Move {values['date']} \"{move.label}\" created")
        self.debug and print(move_values)

        lines = []

        for vals in move_values:
            code = vals.get("account")
            if not code:
                if any(v for v in vals.values()):
                    self.print(1, f"[yellow]- [SKIP] no account provided: {vals}[/yellow]")
                continue

            account = self.get_account(code)
            if not account:
                self.print(1, f"[yellow]- [SKIP] account {code} not found[/yellow]\n  {vals}")

            line = models.Line(
                move=move,
                account=account,
                amount=vals.get("debit") or vals.get("credit"),
                is_debit=bool(vals.get("debit")),
            )

            # print out:
            amount_str = str(line.amount).ljust(12, " ")
            if line.is_debit:
                amount_str = f"[green]+{amount_str}[/green]"
            else:
                amount_str = f"[red]-{amount_str}[/red]"

            self.print(0, f"  {amount_str} | {account.code.ljust(6)} | {account.name}")
            lines.append(line)

        balance = sum(line.debit - line.credit for line in lines)
        self.print(0, " ", "-" * 14, "\n", f"  {balance}")

        if balance != 0:
            self.print(0, f"[yellow]Move balance is not 0: {balance}[/yellow]")
            self.debug and breakpoint()
        self.print(0)
        return move, lines

    # --- Book template import
    @transaction.atomic
    def handle_import_template(self, path, template=None, clear=False, **kwargs):
        import_template.BookTemplateImport().run(path, template_id=template, clear=clear)

    # --- Report template import
    def handle_import_report(self, path, template=None, save=False, clear=False, **kwargs):
        template, sections = import_template.ReportTemplateImport().run(
            path, template_id=template, clear=clear, save=save
        )
        self.print_report(template, sections)
