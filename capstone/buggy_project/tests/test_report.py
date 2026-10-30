from datetime import date

from ledger.models import Transaction
from ledger.report import month_summary, monthly_totals


def tx(day, cents, category="food"):
    return Transaction(date=day, amount_cents=cents, category=category, memo="")


def test_totals_group_by_category():
    txns = [
        tx(date(2024, 3, 5), -1000),
        tx(date(2024, 3, 6), -250),
        tx(date(2024, 3, 7), 5000, "salary"),
    ]
    assert monthly_totals(txns, 2024, 3) == {"food": -1250, "salary": 5000}


def test_other_months_excluded():
    txns = [tx(date(2024, 2, 20), -100), tx(date(2024, 3, 10), -200), tx(date(2024, 4, 2), -300)]
    assert monthly_totals(txns, 2024, 3) == {"food": -200}


def test_includes_last_day_of_month():
    txns = [tx(date(2024, 3, 15), -1000), tx(date(2024, 3, 31), -2500)]
    assert monthly_totals(txns, 2024, 3) == {"food": -3500}


def test_summary_mid_month():
    txns = [tx(date(2024, 3, 2), 10000, "salary"), tx(date(2024, 3, 9), -4000)]
    assert month_summary(txns, 2024, 3) == {
        "income": 10000,
        "expenses": -4000,
        "net": 6000,
        "count": 2,
    }


def test_empty_month():
    assert monthly_totals([], 2024, 3) == {}
