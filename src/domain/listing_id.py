"""Validation for opaque marketplace listing identifiers."""


def validate_listing_id(value: object, field_name: str = "listing_id") -> str:
    """Return an unchanged valid listing ID or raise a precise error."""
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value
