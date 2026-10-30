import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from .models import Transaction


def parse_amount(text: str) -> int:
    """Convert a decimal currency string such as "12.34" or "-5" to cents."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        raise ValueError(f"invalid amount: {text!r}") from None
    return int((value * 100).to_integral_value())


def parse_csv(text: str) -> list[Transaction]:
    """Parse CSV text with columns date,amount,category,memo.

    Blank lines are skipped. Categories are lower-cased and stripped.
    Raises ValueError on a malformed row.
    """
    transactions = []
    reader = csv.DictReader(io.StringIO(text))
    for line_no, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue
        try:
            day = date.fromisoformat(row["date"].strip())
            amount = parse_amount(row["amount"])
        except (KeyError, ValueError, AttributeError) as exc:
            raise ValueError(f"line {line_no}: {exc}") from exc
        transactions.append(
            Transaction(
                date=day,
                amount_cents=amount,
                category=(row.get("category") or "").strip().lower() or "uncategorized",
                memo=(row.get("memo") or "").strip(),
            )
        )
    return transactions
