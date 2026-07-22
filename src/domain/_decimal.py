"""Strict validation for canonical Decimal fields."""

from decimal import Decimal


def require_decimal(
    name: str,
    value: Decimal,
    *,
    non_negative: bool = False,
) -> None:
    """Reject non-Decimal, non-finite, and optionally negative values."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if non_negative and value < Decimal("0"):
        raise ValueError(f"{name} must be non-negative")
