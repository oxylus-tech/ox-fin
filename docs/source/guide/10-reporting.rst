Reports
=======

As for ledger book, reports are based on a provided template file. This
template provide all the structure of the different sections and how to
compute them.

Sections can be computed based on 4 different ways:
- Summing children sections;
- Based on a previous report's section;
- Computing lines using the section code as a lines selector (FIXME: to be removed in favor to formulae);
- Using a formula;



Formula
-------

A formula is essencially a python expression with a custom DSL integration within back
brackets. This DSL allows to select and aggregate ledger book entry lines amount, as it
express a **selector**.

.. code-block:: yaml

    sections:
    - name: Test section
      code: 23
      formula: "`@23|debit`"
    - name: Test section
      code: 24C
      formula: "`@24/5`"
    - name: Test section
      code: 25P
      formula: "`23` + `24C`"

A selector targets either another section or a dataset of lines, and has the two main forms:
- ``[code]``: select another section
- ``[aggr:]?[scope][code][|[filter]]+``: select lines from ledger book

Where:

- ``aggr`` is an aggregation function: ``sum`` (default if not specified), ``max``, ``min``;
- ``scope`` define what we do select:
    - ``@`` (aka state): either the account balance;
    - ``~`` (aka flow): the change within the current period;
- ``code`` selects entry lines in an account by code as:
    - a single account code;
    - a comma-separated list of account codes;
    - an range of account codes split with a single ``/``. ``21/32`` means *all accounts code between 21 and 32 (included)*. ``201/21`` means *all accounts between 201 and 221*;
- ``filters``: one or more dataset filters separated using a ``|``. Filter can optionally take an operator and a value, but most of them don't use it.

    Here are some of them, they select lines using different rules/filters:

    - ``debit``: debit lines;
    - ``credit``: credit lines;
    - ``opening``: opening move lines (not really usefull);
    - ``closing``: closing move lines (not really usefull);
    - Fixed assets filters:
        - ``fixed_asset``: of fixed asset account (determined by the presence of related fields as for amortization/loss/gain);
        - ``asset_dep_exp``: of account used to register an amortization/depreciation (debit on amortization);
        - ``asset_acc_dep``: of account used to register the accumulated amortization/depreciation (credit on amortization)
        - ``asset_gain``: of account used to register gain;
        - ``asset_loss``: of account used to register loss;
    - ``counterpart``: lines that have (or not) a counterpart in the provided accounts:
        - ``counterpart:22,21``: you can provide a list (not a range) of code
        - ``counterpart!:22``: you can exclude too;

Examples:

.. code-block:: yaml

    # Balance of debit lines for account 22->27 with counterpart credit on 6302 or 6301
    @22/27|debit|counterpart:6302,6303
    # Movements of debits on account 23 related to a fixed asset
    ~23|fixed_asset|debit
    # Max value of credits movements on account 22->27
    max:~22/27|credit
    # Target section "25"
    25
    # Target section 25:report
    25:report
