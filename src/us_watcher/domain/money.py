"""Decimal helpers for money/price values.

Prices and money use :class:`decimal.Decimal`, never ``float`` — a raw float in
a price field is a bug, not a rounding nuisance. :class:`DecimalNoFloat` is a
Pydantic-compatible annotated type that rejects raw floats at validation time.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


def to_decimal(value: Any) -> Decimal:
    """Coerce str/int/Decimal to Decimal. Raw ``float`` is rejected."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("float is not allowed for money/price; pass str or Decimal")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"cannot parse Decimal from {value!r}") from exc


class _DecimalNoFloatPydantic:
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(v: Any) -> Decimal:
            if isinstance(v, float):
                raise ValueError("float is not allowed for a price/money field; use str or Decimal")
            return to_decimal(v)

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )


# Use as a field type: `price: DecimalNoFloat`
DecimalNoFloat = Annotated[Decimal, _DecimalNoFloatPydantic()]
