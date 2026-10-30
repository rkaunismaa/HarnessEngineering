# ledger

A small personal-finance library (standard library only). It parses transaction
CSV exports and produces per-category totals for a calendar month.

```python
from ledger.parse import parse_csv
from ledger.report import monthly_totals, month_summary

txns = parse_csv(open("export.csv").read())
monthly_totals(txns, 2024, 3)   # {"groceries": -12034, "salary": 250000}
month_summary(txns, 2024, 3)    # {"income": ..., "expenses": ..., "net": ..., "count": ...}
```

CSV format: a header row `date,amount,category,memo`, dates as `YYYY-MM-DD`,
amounts as decimal currency (`12.34`, `-5`). Amounts are stored as integer cents.

## Running the tests

From this directory:

    python -m pytest tests
