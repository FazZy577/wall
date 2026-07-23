"""Canonical currency-code validation and mismatch errors."""


class CurrencyMismatchError(Exception):
    """Raised before values denominated in different currencies interact."""

    def __init__(self, expected: str, received: str, context: str) -> None:
        self.expected = expected
        self.received = received
        self.context = context
        super().__init__(
            f"Currency mismatch in {context}: expected {expected}, got {received}"
        )


def validate_currency_code(value: object, field_name: str = "currency") -> str:
    """Require an already-normalized three-letter ASCII currency code."""
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    if (
        len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value != value.upper()
    ):
        raise ValueError(
            f"{field_name} must be a normalized three-letter uppercase ASCII code"
        )
    return value
