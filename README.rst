ox-fin
======

This is a temporary project providing basis to later work with Oxylus.

It aims to already provide tools to handle accounting based on file names. It is not
for production and it should only be used for personal purpose.


Features
--------

- Django models for basic double accounting;
- Ledger book templates;
- Import accounts and journals template from CSV file;
- Scan document directory to fullfill book transactions, based on file name format:
  ``[date] - [ref] - [label] - [transactions].[ext]``:

    - ``[date]``: YYYYMMDD formatted date;
    - ``[ref]``: YYYYXXX reference number (eg. ``2025001``);
    - ``[label]``: free form label text;
    - ``[transactions]``: transaction as comma separated list of ``key:value``. Where
      ``key`` is an account code or short-name (provided per user); 

  Example file name: ``20250401 - 2025001 - Sale to Luke - client-debt:100, vat:21.0.pdf``


