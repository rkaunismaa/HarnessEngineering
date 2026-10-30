from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Transaction:
    date: date
    amount_cents: int
    category: str
    memo: str = ""

    @property
    def is_income(self) -> bool:
        return self.amount_cents > 0
