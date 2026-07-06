"""Custom SQLAlchemy column types.

``DecimalString`` stores :class:`~decimal.Decimal` as TEXT so precision is never
lost on either SQLite or Postgres (no binary float round-trips for prices).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from us_watcher.domain.money import to_decimal


class DecimalString(TypeDecorator[Decimal]):
    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return str(to_decimal(value))

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)
