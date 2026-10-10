"""Resolve explicit seed identities for tests using the real packaged detector."""

from functools import cache

from domain.entities.detected_game import Platform
from domain.entities.game_record import ReleaseIdentity
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog


@cache
def seed_identity(name: str, platform: Platform) -> ReleaseIdentity | None:
    return next((entry.release_identity for entry in PackagedGameCatalog().list_games()
                 if entry.canonical_name == name and entry.platform is platform), None)
