from .models import Transaction
from .periods import month_range


def monthly_totals(txns: list[Transaction], year: int, month: int) -> dict[str, int]:
    """Sum amount_cents per category for transactions in the given month."""
    start, end = month_range(year, month)
    totals: dict[str, int] = {}
    for t in txns:
        if not (start <= t.date < end):
            continue
        totals[t.category] = totals.get(t.category, 0) + t.amount_cents
    return totals


def month_summary(txns: list[Transaction], year: int, month: int) -> dict[str, int]:
    """Income, expenses (as a negative number), net and count for the month."""
    start, end = month_range(year, month)
    in_month = [t for t in txns if start <= t.date < end]
    income = sum(t.amount_cents for t in in_month if t.is_income)
    expenses = sum(t.amount_cents for t in in_month if not t.is_income)
    return {
        "income": income,
        "expenses": expenses,
        "net": income + expenses,
        "count": len(in_month),
    }
