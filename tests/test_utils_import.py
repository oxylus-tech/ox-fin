import csv

import pytest

from fin.models import Account
from fin.utils.csv_import import ModelCSVImport

@pytest.fixture
def csv_data():
    return [
        ["name", "code", "type"],
        ["Name 1", "10", "asset"],
        ["Name 2", "20", "revenue"]
    ]


@pytest.fixture
def csv_file(tmp_path, csv_data):
    path = tmp_path / "test.csv"
    with open(path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in csv_data:
            writer.writerow(row)
    return path


@pytest.fixture
def csv_import(book_template):
    return ModelCSVImport(Account, kwargs={"template": book_template})
    

class TestModelCSVImport:
    def test_run(self, book_template, csv_import, csv_file, csv_data):
        objs = csv_import.run(csv_file)
        assert len(objs) == len(csv_data)-1
        assert all(o.template == book_template for o in objs)
        for obj, dat in zip(objs, csv_data[1:]):
            assert obj.name == dat[0]
            assert obj.code == dat[1]
            assert obj.type == Account.Type.from_str(dat[2])
