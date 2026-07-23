"""Normalize real Wallapop identifiers at the external-data boundary."""


def normalize_wallapop_listing_id(value: object) -> str | None:
    """Normalize supported Wallapop payload ID formats without fallback."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, int):
        return str(value)
    return None
