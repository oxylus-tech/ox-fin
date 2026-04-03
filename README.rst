ox-fin
======

This project provides a ledger book and accounting engine. We later want to integrate
it into Oxylus.

Features
--------

**Ledger book and journal entries management:**

    - Ledger book creation and edition;
    - Assets and amortization management;
    - Balance and various checks integration;
    - Import ledger book from XLSX/ODS files;
    - Tasks automatizations, as balance sheet and amortizations (more to come);
    - Easilly extensible;

**Extensible ledger book template system:**

    - Each ledger book can be linked to a different template with custom accounts and journals;
    - Import the template from schema YAML file;
    - Specify fine-grained use case for account (as related gain/loss account, amortization journal, etc).

**Reporting engine:**

    - Create and edit templates to generate reports;
    - Load templates from YAML schema files;
    - Complexe formula computation;

**Command line tool:**

    - Complete command line tool interface to handle all accounting tasks;
    - Create, import and view ledger books;
    - Generate and view amortizations and reports;
    - Import book and report templates;
    - It all starts from: ``./manage.py ox_fin``

**YAML schemas:**

    - Load templates from YAML files;
    - Composition: include and reuse other schemas;

**Other features we want to develop:**

    - Reporting: validation formulas;
    - More validation tests on books and reports;
    - XBRL: integrate xbrl into report generation;
    - XBRL: load report templates from XBRL taxonomy;
