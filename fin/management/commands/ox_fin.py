from datetime import timedelta, date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from rich import print, align
from rich.table import Table

from fin import models, loaders
from fin.engine.report import ReportBuilder
from fin.utils import checks


def as_date(val):
    if "-" in val:
        val = val.split("-")
    elif "/" in val:
        val = val.split("/")
    else:
        raise ValueError("The provided value is not a valid date. It must contains separators '/' or '-'.")
    return date(*val)


def create_table(title, columns, title_style="b yellow", expand=True):
    t = Table(title=title, title_style=title_style, expand=expand)
    for col in columns:
        if isinstance(col, str):
            t.add_column(col)
        else:
            t.add_column(col[0], style=col[1])
    return t


class Command(BaseCommand):
    help = "Ledger book import for home's data."

    verbosity = 0
    debug = False

    book = None
    journals: dict[str, models.Journal] = None
    accounts: dict[str, models.Account] = None
    accounts_qs = None

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers()

        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--debug", action="store_true")

        # --- Main
        group = subparsers.add_parser("info", help="Display various informations")
        group.set_defaults(func=self.handle_info)

        # --- Book related actions
        group = subparsers.add_parser("create-book", help="Create a new book")
        group.set_defaults(func=self.handle_create_book, is_book_template=True)
        group.add_argument("title", metavar="TITLE", help="Title of the ledger book.")
        group.add_argument("--template", "-t", required=True, help="Book template to use.")
        group.add_argument("--description", "-d", help="Book description.")
        group.add_argument("--path", "-p", help=f"Book documents path withing {settings.BOOKS_ROOT}.")

        group = subparsers.add_parser("import", help="Import a ledger book from XLS or ODS file.")
        group.set_defaults(func=self.handle_import)
        group.add_argument("path", metavar="PATH", type=Path, action="append", help="Document path")
        group.add_argument("--book", "-b", type=int, help="Select the book (by id)")
        group.add_argument("--year", "-y", type=int, help="Filter by year")
        group.add_argument("--save", "-s", action="store_true", help="Save data in db")
        group.add_argument(
            "--clear",
            "-c",
            action="store_true",
            help="Delete all book data before import. When year is selected, only the transactions of this year will be removed.",
        )

        group = subparsers.add_parser("summary", help="Print ledger book's moves summary")
        group.set_defaults(func=self.handle_summary)
        group.add_argument("--book", "-b", type=int, required=True, help="Select the book (by id)")
        group.add_argument("--year", "-y", type=int, help="Filter by year")
        group.add_argument("--balance", action="store_true", help="Show accounts balance")

        # --- Book template related actions
        group = subparsers.add_parser("accounts")
        group.set_defaults(func=self.handle_accounts, is_book_template=True)
        group.add_argument("--template", "-t", type=int, required=True, help="Book template")

        group = subparsers.add_parser("import-template", help="Import a book template from a YAML file.")
        group.set_defaults(func=self.handle_import_template, is_book_template=True)
        group.add_argument("path", metavar="PATH", type=Path, help="Book template YAML file")
        group.add_argument(
            "--template", "-t", type=int, help="Book template ID to update (instead of creating a new one."
        )
        group.add_argument("--save", "-s", action="store_true", help="Save data in db")
        group.add_argument(
            "--clear", "-c", action="store_true", help="Trunk accounts and journals not present in the YAML."
        )

        # --- Reports
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

        group = subparsers.add_parser(
            "report",
            help=(
                "Generate a new report for the provided ledger book and report template.\n"
                "You must provide a period, either using `--year` argument or `--start` and `--end` one."
            ),
        )
        group.set_defaults(func=self.handle_report)
        group.add_argument("--book", "-b", type=int, required=True, help="Select the book (by id)")
        group.add_argument("--template", "-t", type=int, required=True, help="Report template ID")
        group.add_argument("--year", "-y", type=int, help="Annual report year.")
        group.add_argument("--start", type=as_date, help="Report period start date.")
        group.add_argument("--end", type=as_date, help="Report period end date.")

    def print(self, level, *args, **kwargs):
        if level <= self.verbosity:
            print(*args, **kwargs)

    @transaction.atomic
    def handle(self, func, verbose=0, debug=False, **kwargs):
        self.verbosity = verbose and 1 or 0
        self.debug = debug
        self.setup(**kwargs)
        return func(**kwargs)

    def setup(self, book=None, template=None, is_book_template=False, **_):
        if book:
            self.book = models.Book.objects.select_related("template").get(pk=book)
            template = template or self.book.template

        if template and (book or is_book_template):
            if isinstance(template, models.BookTemplate):
                self.template = template
            else:
                self.template = models.BookTemplate.objects.get(pk=template)

            journals = models.Journal.objects.filter(template_id=template)
            self.accounts_qs = models.Account.objects.filter(template_id=template).order_by("code")
            self.journals = {journal.code: journal for journal in journals}

            self.accounts = {account.code: account for account in self.accounts_qs}
            self.accounts.update(
                {
                    account.code.ljust(6, "0"): account
                    for account in self.accounts_qs
                    if len(account.code) < 6 and account.code not in self.accounts
                }
            )

    def group_lines(self, lines):
        # not the most efficient, but avoids to have to save to db
        # to display stuffs.
        for account in self.accounts_qs:
            yield account, [line for line in lines if line.account == account]

    def get_lines(self, period=None):
        lines = (
            models.Line.objects.filter(move__book=self.book)
            .select_related("move")
            .order_by("move__date", "move__reference", "-is_debit")
        )
        if isinstance(period, int):
            lines = lines.filter(move__date__year=period)
        elif isinstance(period, tuple) and len(period) == 2:
            lines = lines.filter(move__date__gte=period[0], move__date__lte=period[1])
        else:
            raise ValueError("Invalid period (either a year or a tuple of two dates)")
        return lines

    # ---- info
    def handle_info(self, **kwargs):
        table = create_table("Book Template", [("ID", "cyan"), "Title", "Name", "Description", "Accounts", "Journals"])

        for obj in models.BookTemplate.objects.all():
            table.add_row(
                str(obj.pk),
                obj.title,
                obj.name,
                obj.description,
                str(obj.accounts.all().count()),
                str(obj.journals.all().count()),
            )
        print(table, "\n")

        table = create_table("Report Template", [("ID", "cyan"), "Title", "Name", "Description", "Sections"])

        for obj in models.ReportTemplate.objects.all():
            table.add_row(
                str(obj.pk),
                obj.title,
                obj.name,
                obj.description,
                str(obj.sections.all().count()),
            )
        print(table, "\n")

        table = Table("Book", [("ID", "cyan"), "Title", "Description", "Template", "Moves"])

        for obj in models.Book.objects.all():
            table.add_row(
                str(obj.pk),
                obj.title,
                obj.description,
                f"{obj.template_id}",
                str(obj.moves.all().count()),
            )
        print(table, "\n")

    # ---- create book
    def handle_create_book(self, title, template, description=None, path=None, **kwargs):
        book = models.Book.objects.create(title=title, template=self.template, description=description, path=path)
        print(f"Created a new book, with id: {book.id}")
        print("You can run [cyan]ox_fin info[/cyan] command if you forget it.")

    # ---- import
    def handle_import(self, path, year=None, save=False, clear=False, **kwargs):
        moves, lines, assets = [], [], []
        loader = loaders.BookSheetLoader(self.book, year=year)
        for p in path:
            results = loader.run(p, save=save, clear=clear)
            moves.extend(results["moves"])
            lines.extend(results["lines"])
            assets.extend(results["assets"])

        moves.sort(key=lambda m: (m.date, m.reference or ""))
        lines.sort(key=lambda li: (li.move.date, li.move.reference or "", not li.is_debit))

        if year:
            moves = [m for m in moves if m.date.year == year]
            lines = [line for line in lines if line.move.date.year == year]

        print("")
        self.summary(self.book, lines, details=True)

        if assets:
            print("")
            self.summary_assets(self.book, assets, f"{self.book.title} - Assets")

        print("")
        checks.check_lines_balance(lines)

    # ---- summary
    def handle_summary(self, year=None, balance=False, assets=False, **kwargs):
        lines = self.get_lines(period=year)
        self.summary(self.book, lines, details=True)

        if balance:
            print("")
            self.balance(self.book, lines)

        if assets:
            print("")
            self.summary_assets(self.book, self.book.assets)

    def summary(self, book, lines, details=False):
        t = create_table(book.title, [("Account", "cyan"), "Name", "Debit", "Credit", ("Balance", "cyan")])

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
                        f"[i][yellow]{line.move.date}[/yellow] [magenta]{line.move.journal.code.ljust(3)}[/magenta] {line.move.description}[/i]",
                        str(line.debit),
                        str(line.credit),
                        f"[{color}]{balance}[/{color}]",
                    )

        print(t)

    def summary_assets(self, book, assets, details=False):
        t = create_table(
            f"{book.title} - Assets",
            [
                ("Date", "yellow"),
                "Reference",
                "Description",
                "Type",
                "Entry",
                ("Value", "cyan"),
                ("Amort. Value", "cyan"),
            ],
        )

        for asset in assets:
            schedules = asset.amortizations.all()

            t.add_row(
                str(asset.date),
                asset.reference,
                asset.description,
                asset.get_type_display(),
                asset.move.reference,
                str(asset.value),
                schedules.exists() and str(asset.get_amortized_value()) or "",
            )

            for schedule in schedules:
                t.add_row(
                    "",
                    "",
                    f"[i][yellow]{schedule.start_date}[/yellow] -> [yellow]{schedule.end_date}[/yellow]",
                    f"[i]{schedule.get_frequency_display()} {schedule.get_method_display()}[/i]",
                )

        print(t)

    def balance(self, book, lines):
        t = create_table(f"{book.title} - Balance", [("Account", "cyan"), "Name", "Debit", "Credit"])

        total_debit, total_credit = Decimal("0"), Decimal("0")
        for account, ls in self.group_lines(lines):
            if not ls:
                continue

            debit = sum(line.debit for line in ls)
            credit = sum(line.credit for line in ls)
            if debit > credit:
                b0, b1 = debit - credit, 0
                t.add_row(account.code, account.name, str(b0), "")
            else:
                b0, b1 = 0, credit - debit
                t.add_row(account.code, account.name, "", str(b1))

            total_debit += b0
            total_credit += b1

        color = "green" if total_debit == total_credit else "red"
        t.add_section()
        t.add_row(
            "",
            align.Align("[b]Totals[/b]", "right"),
            f"[{color}]{total_debit}[/{color}]",
            f"[{color}]{total_credit}[/{color}]",
        )
        print(t)

        if total_debit != total_credit:
            print("")
            checks.check_lines_balance(lines)

    def monthly_summary(self, lines, **kw):
        min_date, max_date = min(line.move.date for line in lines), max(line.move.date for line in lines)
        offset = min_date.replace(day=1)

        while offset <= max_date:
            offset_2 = (offset + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            lines_ = [line for line in lines if offset <= line.move.date <= offset_2]
            self.summary(lines_, f"{offset.year} - {offset.month}", **kw)
            offset = offset_2 + timedelta(days=1)

    # --- import-template
    @transaction.atomic
    def handle_import_template(self, path, template=None, clear=False, save=False, **kwargs):
        print(f"Start book template import from [yellow]`{path}`[/yellow]...")
        results = loaders.BookTemplateLoader().run(path, template_id=template, clear=clear, save=save)

        template = results["template"]
        accounts = results["accounts"]
        journals = results["journals"]

        print(f"[green]Success![/green] The book template [yellow]`{template.title}`[/yellow] has been imported:")
        print(f"- {len(accounts)} new/updated accounts;")
        print(f"- {len(journals)} new/updated journals;")

    # ---- accounts
    def handle_accounts(self, template, **kwargs):
        template = models.BookTemplate.objects.get(id=template)
        t = create_table(template.name, [("Account", "cyan"), "Name", "Type", ""])

        for account in self.accounts_qs.order_by("code"):
            ty = "debit" if account.is_debit else "credit"
            ty_2 = str(account.Type(account.type).name)
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

    # --- import-report
    def handle_import_report(self, path, template=None, save=False, clear=False, **kwargs):
        print(f"Start report template import from [yellow]`{path}`[/yellow]...")
        results = loaders.ReportTemplateLoader().run(path, template_id=template, clear=clear, save=save)

        template, sections = results["template"], results["sections"]

        print(f"[green]Success![/green] The report template [yellow]`{template.title}`[/yellow] has been imported:")
        print(f"- {len(sections)} new/updated root sections;")
        self.print_report(results["template"], results["sections"])

    # ---- report
    def handle_report(self, template, year=None, start=None, end=None, **kwargs):
        if not year:
            if not start or not end:
                raise ValueError("You must provide a period, either using --year or --start and --end.")
            period = (start, end)
        else:
            period = (date(year, 1, 1), date(year, 12, 31))

        template = models.ReportTemplate.objects.get(pk=template)
        lines = self.get_lines(period=period)

        builder = ReportBuilder(template, self.book)
        report, results = builder.build(lines, period=period)
        sections = template.sections.filter(parent__isnull=True).order_by("order")
        self.print_report(template, sections, results)

    _report_tags = {
        0: "b",
        1: "b yellow",
        2: "b",
        4: "i",
    }

    def print_report(self, template, sections, results=None):
        if results:
            last_col = ("Value", "cyan")
        else:
            last_col = ("Formula", "italic")
        t = create_table(template.title, ["Label", ("Code", "cyan"), last_col])
        self.print_report_sections(t, sections, results=results)
        print(t)

    def print_report_sections(self, t, sections, depth=0, results=None):
        for section in sections:
            if tag := self._report_tags.get(depth):
                name = f"[{tag}]{section.name}[/{tag}]"
            else:
                name = section.name

            args = [
                (depth * 2 - 2) * " " + name,
                section.code or "",
            ]
            if results:
                if result := results.get(section.id):
                    if result.value is None:
                        result = ""
                    else:
                        result = str(round(result.value, 2))
                else:
                    result = ""
                args.append(result)
            else:
                args.append(
                    section.previous
                    and f"N-1: {section.previous.code}"
                    or section.formula
                    or f"Weight: {section.weight or ''}"
                )

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
