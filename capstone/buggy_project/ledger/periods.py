import calendar
from datetime import date


def month_range(year: int, month: int) -> tuple[date, date]:
    """Return (first_day, last_day) of the month, both inclusive."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    last = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, last)
    return start, end


def previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1
