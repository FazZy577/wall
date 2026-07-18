"""Test to verify the project structure is set up correctly."""


def test_project_structure() -> None:
    """Verify that basic imports work."""
    # Domain layer
    # Shared utilities
    import shared

    # Application layer
    from application import use_cases
    from domain import entities, interfaces, value_objects

    # Infrastructure layer
    from infrastructure import marketplaces, repositories

    # If we can import these, the structure is correct
    assert entities is not None
    assert interfaces is not None
    assert value_objects is not None
    assert use_cases is not None
    assert marketplaces is not None
    assert repositories is not None
    assert shared is not None


def test_wallapop_client_exists() -> None:
    """Verify that WallapopClient is importable."""
    from infrastructure.marketplaces.wallapop.client import WallapopClient

    client = WallapopClient()
    assert client is not None
