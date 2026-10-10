"""B08 identity migration, renamed titles, provisional records and products."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from application.interfaces.listing_observation_recorder import ListingObservation
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from domain.entities.candidate_classification import CandidateDisposition
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.game_identity import GameIdentity
from domain.entities.game_record import (
    ExternalGameReference,
    GameRecord,
    IdentityStatus,
    MediaFormat,
    ReleaseIdentity,
)
from domain.interfaces.comparable_filter import ComparableFilterInput
from domain.interfaces.game_detector import ListingText
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.catalogs.sqlite_game_registry import SqliteGameRegistry
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.discovery.sqlite_catalog_discovery_recorder import (
    SqliteCatalogDiscoveryRecorder,
)
from infrastructure.filters.rule_based_comparable_filter import RuleBasedComparableFilter
from infrastructure.matching.platform_lexical_matcher import PlatformLexicalMatcher

pytestmark = pytest.mark.integration


def detection(name="First Name", identity=None):
    identity = identity or ReleaseIdentity("game-1", "release-1", Platform.PS5)
    return DetectedGame(name, name, identity.platform, 1.0, DetectionMethod.EXACT_MATCH, identity)


def test_rename_preserves_identity_detection_and_cache_after_restart(tmp_path):
    path = tmp_path / "registry.sqlite3"
    registry = SqliteGameRegistry(path)
    original = GameRecord("game-1", "First Name", status=IdentityStatus.CONFIRMED)
    registry.save_game(original)
    registry.save_release(ReleaseIdentity("game-1", "release-1", Platform.PS5))
    before = FuzzyGameDetector(registry).detect_games(ListingText("First Name PS5", ""))[0]
    registry.save_game(replace(original, canonical_name="Renamed Adventure"))
    restarted = SqliteGameRegistry(path)
    after = FuzzyGameDetector(restarted).detect_games(ListingText("First Name PS5", ""))[0]
    assert after.canonical_name == "Renamed Adventure"
    assert GameIdentity.from_game(before) == GameIdentity.from_game(after)
    assert hash(GameIdentity.from_game(before)) == hash(GameIdentity.from_game(after))
    assert DefaultOpportunityScanner._build_comparable_cache_key(before) == DefaultOpportunityScanner._build_comparable_cache_key(after)
    assert RuleBasedComparableFilter().is_valid_comparable(before, ComparableFilterInput(
        "Renamed Adventure PS5", price=Decimal("20"), detected_games=(after,),
    ))


@pytest.mark.parametrize("changes", [
    {"release_id": "ps4-release", "platform": Platform.PS4},
    {"release_id": "deluxe-release", "edition": "deluxe"},
    {"release_id": "digital-release", "media_format": MediaFormat.DIGITAL},
    {"game_id": "other-game", "release_id": "other-release"},
])
def test_different_products_never_share_identity_or_comparable_cache(changes):
    first = detection()
    second = detection(identity=replace(first.release_identity, **changes))
    assert GameIdentity.from_game(first) != GameIdentity.from_game(second)
    assert DefaultOpportunityScanner._build_comparable_cache_key(first) != DefaultOpportunityScanner._build_comparable_cache_key(second)
    assert not RuleBasedComparableFilter().is_valid_comparable(first, ComparableFilterInput(
        "First Name PS5", price=Decimal("20"), detected_games=(second,),
    ))


def test_legacy_name_cannot_impersonate_registered_identity():
    confirmed = detection()
    legacy = replace(confirmed, release_identity=None)
    assert GameIdentity.from_game(confirmed) != GameIdentity.from_game(legacy)


def test_provisional_game_and_release_are_not_detection_candidates(tmp_path):
    registry = SqliteGameRegistry(tmp_path / "registry.sqlite3")
    registry.save_game(GameRecord("pending", "Tomorrow Adventure"))
    release = ReleaseIdentity("pending", "pending-release", Platform.PS5, status=IdentityStatus.PROVISIONAL)
    registry.save_release(release)
    assert registry.list_games() == ()
    assert FuzzyGameDetector(registry).detect_games(ListingText("Tomorrow Adventure PS5", "")) == []
    candidate = detection("Tomorrow Adventure", release)
    with pytest.raises(ValueError, match="provisional"):
        GameIdentity.from_game(candidate)
    classification = RuleBasedCandidateEligibilityPolicy().classify(
        CandidateListing("candidate", "Tomorrow Adventure PS5", "", Decimal("2"), "EUR", ""), (candidate,),
    )
    assert classification.disposition is CandidateDisposition.AMBIGUOUS


def test_external_reference_collision_rolls_back_update(tmp_path):
    registry = SqliteGameRegistry(tmp_path / "registry.sqlite3")
    ref = ExternalGameReference("test-provider", "123")
    registry.save_game(GameRecord("first", "Game One", external_references=(ref,)))
    with pytest.raises(sqlite3.IntegrityError):
        registry.save_game(GameRecord("second", "Game Two", external_references=(ref,)))
    assert registry.get_game("second") is None
    assert registry.get_game("first").external_references == (ref,)


def test_seed_migration_is_repeatable_and_does_not_undo_local_renames(tmp_path):
    registry = SqliteGameRegistry(tmp_path / "registry.sqlite3")
    seed = PackagedGameCatalog().list_games()
    registry.import_seed(seed)
    first = seed[0]
    game = registry.get_game(first.release_identity.game_id)
    registry.save_game(replace(game, canonical_name="Locally Renamed Game"))
    registry.import_seed(seed)
    assert len(registry.list_games()) == len(seed)
    assert registry.get_game(game.game_id).canonical_name == "Locally Renamed Game"
    assert len({entry.release_identity.release_id for entry in seed}) == len(seed)


@pytest.mark.parametrize("text", ["Switch 2", "Nintendo Switch 2", "SWITCH2", "Switch-2"])
def test_switch_two_never_falls_back_to_original_switch(text):
    mentions = PlatformLexicalMatcher().find_mentions(text)
    assert [mention.platform for mention in mentions] == [Platform.SWITCH_2]
    detector = FuzzyGameDetector(PackagedGameCatalog())
    assert not any(game.platform is Platform.SWITCH for game in detector.detect_games(
        ListingText(f"Mario Kart 8 Deluxe {text}", "")
    ))


@pytest.mark.asyncio
async def test_unknown_observation_gets_one_provisional_id_across_versions(tmp_path):
    path = tmp_path / "observations.sqlite3"
    observation = ListingObservation("new", "Tomorrow Game Switch 2", "", Decimal("10"),
                                     "EUR", datetime.now(UTC), "unknown")
    await SqliteCatalogDiscoveryRecorder(path).record_observation(observation)
    await SqliteCatalogDiscoveryRecorder(path).record_observation(replace(observation, description="More detail"))
    with closing(sqlite3.connect(path)) as connection:
        ids = connection.execute("SELECT provisional_game_id FROM listing_observations").fetchall()
    assert len(ids) == 2 and ids[0] == ids[1] and ids[0][0]
    registry = SqliteGameRegistry(path)
    assert registry.get_game(ids[0][0]).status is IdentityStatus.PROVISIONAL
    assert registry.list_games() == ()


def test_release_id_cannot_be_reused_for_a_different_platform(tmp_path):
    registry = SqliteGameRegistry(tmp_path / "registry.sqlite3")
    registry.save_game(GameRecord("game", "Example", status=IdentityStatus.CONFIRMED))
    release = ReleaseIdentity("game", "release", Platform.PS5)
    registry.save_release(release)
    with pytest.raises(ValueError, match="product"):
        registry.save_release(replace(release, platform=Platform.PS4))
    assert registry.list_games()[0].platform is Platform.PS5


def test_existing_local_registry_boots_without_loading_packaged_json(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from domain.interfaces.marketplace_search import IMarketplaceSearch
    from presentation.cli.composition import build_operational_runtime
    from tests.integration.test_observation_persistence import config_at

    config = config_at(tmp_path)
    registry = SqliteGameRegistry(config.persistence.database_path)
    registry.save_game(GameRecord("local-only", "Local Adventure", status=IdentityStatus.CONFIRMED))
    registry.save_release(ReleaseIdentity("local-only", "local-release", Platform.SWITCH_2))
    def reject_seed():
        raise AssertionError("Existing local registry must not depend on packaged JSON")
    monkeypatch.setattr("presentation.cli.composition.PackagedGameCatalog", reject_seed)
    runtime = build_operational_runtime(config, AsyncMock(spec=IMarketplaceSearch))
    games = runtime.search_orchestrator.game_detector.detect_games(ListingText("Local Adventure Switch 2", ""))
    assert games[0].release_identity.game_id == "local-only"
    assert games[0].platform is Platform.SWITCH_2


@pytest.mark.asyncio
async def test_existing_unknown_observation_is_backfilled_without_rescanning(tmp_path):
    path = tmp_path / "old.sqlite3"
    recorder = SqliteCatalogDiscoveryRecorder(path)
    await recorder.record_observation(ListingObservation(
        "old", "Unknown Adventure", "", Decimal("10"), "EUR", datetime.now(UTC), "unknown",
    ))
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE listing_observations SET provisional_game_id=NULL")
        connection.execute("DELETE FROM games")
    recorder.initialize()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT seen_count, provisional_game_id IS NOT NULL FROM listing_observations").fetchone() == (1, 1)
        assert connection.execute("SELECT status FROM games").fetchone() == ("provisional",)
