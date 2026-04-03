ox-fin
======

This project provides a ledger book and accounting engine. We later want to integrate
it into `Oxylus <http://oxylus.app>`_ (`main repository <https://github.com/oxylus-tech/oxylus>`_) 
and provide full featured interface.

The project is still under development, though providing the basic functionalities of a double accouting
software (check *Features* section to know what is already there). Since we're developping it without
funding, we do it on our free time.


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

Technical overview
------------------

As any other Oxylus application, this application is a Django one. Integration into Oxylus will bring some changes, however
we first focused on having a complete and correct accounting engine. We currently are taking belgian accounting system as
real-world case scenario.

Mains models (by modules):

- ``book_template``: Book template, accounts and journals;
- ``book``: the ledger book, journal entry and entry lines;
- ``report``: the report and its sections and the template;

Basically, templates describe how the data are organized or should be computed, whilst the counterpart is the result of their
application.

Schemas
.......

Schemas are loaded from YAML files, and implemented as Pydantic models (then loaded into database using different loaders).
We added the following tags to allow composition in the files:

- ``!include [name] [path]``: include another file at the provided ``path`` (can be relative to the current file) and make its
  data available under ``name``.
- ``!ref [target]``: copy the content of the target in-place. The ``target`` is the dotted path to a file's content.

Example:

.. code-block:: yaml

  name: my_custom_schema
  includes:
    - !include balance ./my_balance.yaml
    - !include foo ./foo.yaml
  sections:
    # copy to the first item of the `sections` list of `balance` file in-place
    - !ref balance.sections.0

There are currently two kind of schemas, that you can look up for example in ``data/be/`` folder:

- book template: define a book template, journals, accounts and various information;
- report: provide report and section templates, calculation formulas, etc;

