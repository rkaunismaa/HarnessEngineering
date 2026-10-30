from datetime import date

import pytest

from ledger.periods import month_range, previous_month


def test_month_range_is_inclusive_of_last_day():
    assert month_range(2024, 3) == (date(2024, 3, 1), date(2024, 3, 31))


def test_month_range_february():
    assert month_range(2023, 2)[1] == date(2023, 2, 28)
    assert month_range(2024, 2)[1] == date(2024, 2, 29)


def test_month_range_invalid_month():
    with pytest.raises(ValueError):
        month_range(2024, 13)


def test_previous_month():
    assert previous_month(2024, 3) == (2024, 2)
    assert previous_month(2024, 1) == (2023, 12)
