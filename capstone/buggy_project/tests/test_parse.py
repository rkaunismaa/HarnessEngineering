from datetime import date

import pytest

from ledger.parse import parse_amount, parse_csv

CSV = """date,amount,category,memo
2024-03-01,12.34,Groceries,milk
2024-03-02,-5,Fun,
,,,
2024-03-03,2500.00,Salary,march pay
"""


def test_parse_amount():
    assert parse_amount("12.34") == 1234
    assert parse_amount("-5") == -500
    assert parse_amount(" 0.05 ") == 5


def test_parse_amount_invalid():
    with pytest.raises(ValueError):
        parse_amount("abc")


def test_parse_csv_rows():
    txns = parse_csv(CSV)
    assert len(txns) == 3
    assert txns[0].date == date(2024, 3, 1)
    assert txns[0].amount_cents == 1234
    assert txns[0].category == "groceries"
    assert txns[1].memo == ""
    assert txns[2].amount_cents == 250000


def test_parse_csv_bad_row_reports_line():
    with pytest.raises(ValueError, match="line 2"):
        parse_csv("date,amount,category,memo\nnot-a-date,1,x,y\n")
