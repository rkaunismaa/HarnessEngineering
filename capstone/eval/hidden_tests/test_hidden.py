from datetime import date

import pytest

from ledger.models import Transaction
from ledger.report import month_summary, monthly_totals


def tx(day, cents=100, category="x"):
    return Transaction(date=day, amount_cents=cents, category=category, memo="")


def test_last_day_included():
    assert monthly_totals([tx(date(2024, 3, 31))], 2024, 3) == {"x": 100}


def test_first_day_included():
    assert monthly_totals([tx(date(2024, 3, 1))], 2024, 3) == {"x": 100}


def test_next_month_first_day_excluded():
    assert monthly_totals([tx(date(2024, 4, 1))], 2024, 3) == {}


def test_previous_month_last_day_excluded():
    assert monthly_totals([tx(date(2024, 2, 29))], 2024, 3) == {}


@pytest.mark.parametrize(
    "year,last",
    [(2024, 29), (2023, 28), (2000, 29), (1900, 28)],
)
def test_february_last_day(year, last):
    txns = [tx(date(year, 2, last), 7), tx(date(year, 3, 1), 900)]
    assert monthly_totals(txns, year, 2) == {"x": 7}


def test_december_rollover():
    txns = [tx(date(2024, 12, 31), 5), tx(date(2025, 1, 1), 70), tx(date(2024, 11, 30), 900)]
    assert monthly_totals(txns, 2024, 12) == {"x": 5}
    assert monthly_totals(txns, 2025, 1) == {"x": 70}


def test_summary_counts_last_day():
    txns = [tx(date(2024, 5, 31), -300), tx(date(2024, 5, 1), 1000), tx(date(2024, 6, 1), 5)]
    assert month_summary(txns, 2024, 5) == {"income": 1000, "expenses": -300, "net": 700, "count": 2}
