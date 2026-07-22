"""P1.1/P1.6 tests for execution-scoped comparable collection reuse."""

from dataclasses import fields
from unittest.mock import AsyncMock, Mock

import pytest

from application.interfaces.opportunity_scanner import PipelineStage, ScanResult
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform


def game(
    name: str = "Grand Theft Auto V",
    platform: Platform = Platform.PS4,
    alias: str = "GTA V",
) -> DetectedGame:
    return DetectedGame(name, alias, platform, 1.0, DetectionMethod.ALIAS_MATCH)


def listing(identifier: str, detected_game: DetectedGame, price: float = 10.0) -> CandidateListing:
    return CandidateListing(
        listing_id=identifier,
        title=(
            f"{detected_game.matched_text} {detected_game.canonical_name} "
            f"{detected_game.platform.value}"
        ),
        description="",
        price=price,
        currency="EUR",
        url=f"https://example.test/{identifier}",
    )


def comparable(
    identifier: str, detected_game: DetectedGame, price: float = 20.0
) -> ComparableListing:
    return ComparableListing(
        listing_id=identifier,
        title=f"{detected_game.matched_text} {detected_game.platform.value}",
        description="",
        price=price,
        currency="EUR",
        detected_game=detected_game,
        url=f"https://example.test/{identifier}",
    )


def test_scan_result_exposes_only_comparable_cache_metrics() -> None:
    field_names = {field.name for field in fields(ScanResult)}
    cache_fields = {name for name in field_names if "cache_" in name}

    assert cache_fields == {"comparable_cache_hits", "comparable_cache_misses"}


@pytest.fixture
def cache_scanner() -> tuple[DefaultOpportunityScanner, dict[str, Mock]]:
    dependencies = {
        name: Mock()
        for name in (
            "collector",
            "builder",
            "statistics",
            "outliers",
            "estimator",
            "detector",
        )
    }
    dependencies["collector"] = AsyncMock()
    scanner = DefaultOpportunityScanner(
        game_detector=Mock(),
        price_collector=dependencies["collector"],
        dataset_builder=dependencies["builder"],
        statistics=dependencies["statistics"],
        outlier_removal=dependencies["outliers"],
        market_estimator=dependencies["estimator"],
        arbitrage_detector=dependencies["detector"],
    )
    dependencies["collector"].collect_comparables.return_value = [
        comparable("comparable", game())
    ]
    scanner.game_detector.detect_games.side_effect = lambda text: (
        [game(platform=Platform.PS5)]
        if "ps5" in text.title.casefold()
        else [game("Red Dead Redemption 2", alias="RDR2")]
        if "red dead redemption 2" in text.title.casefold()
        else [game()]
    )
    dataset = Mock(sample_size=5)
    dependencies["builder"].build.return_value = dataset
    dependencies["statistics"].calculate.return_value = Mock()
    dependencies["outliers"].remove_outliers.return_value = Mock(
        clean_dataset=dataset,
        removed_count=0,
    )
    dependencies["estimator"].estimate.return_value = Mock(
        estimated_price=20.0,
        confidence_score=0.8,
    )

    def make_opportunity(candidate: CandidateListing, estimate: Mock) -> Mock:
        return Mock(
            listing=candidate,
            listing_price=candidate.price,
            market_estimate=estimate,
            recommendation="BUY",
            opportunity_score=100.0 - candidate.price,
        )

    dependencies["detector"].detect.side_effect = make_opportunity
    return scanner, dependencies


@pytest.mark.asyncio

async def test_same_game_collects_once_and_values_each_candidate(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, mocks = cache_scanner
    candidates = [listing(str(index), game(), 5.0 + index) for index in range(5)]

    result = await scanner.scan_multiple(candidates)

    assert scanner.price_collector.collect_comparables.await_count == 1
    assert mocks["collector"].collect_comparables.await_count == 1
    assert mocks["builder"].build.call_count == 5
    assert mocks["statistics"].calculate.call_count == 10
    assert mocks["outliers"].remove_outliers.call_count == 5
    assert mocks["estimator"].estimate.call_count == 5
    assert mocks["detector"].detect.call_count == 5
    assert result.comparable_cache_misses == 1
    assert result.comparable_cache_hits == 4
    assert result.comparable_cache_misses == 1
    assert result.comparable_cache_hits == 4


@pytest.mark.asyncio

async def test_different_games_have_different_valuations(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, _ = cache_scanner
    result = await scanner.scan_multiple(
        [listing("gta", game()), listing("rdr", game("Red Dead Redemption 2", alias="RDR2"))]
    )
    assert scanner.price_collector.collect_comparables.await_count == 2
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (2, 0)


@pytest.mark.asyncio

async def test_same_name_on_different_platforms_is_not_shared(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, _ = cache_scanner
    result = await scanner.scan_multiple(
        [listing("ps4", game()), listing("ps5", game(platform=Platform.PS5))]
    )
    assert scanner.price_collector.collect_comparables.await_count == 2
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (2, 0)


@pytest.mark.asyncio

async def test_aliases_and_normalized_canonical_name_share_valuation(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, _ = cache_scanner
    games = [
        game(" Grand Theft  Auto V ", alias="GTA V"),
        game("grand theft auto v", alias="GTA5"),
        game("GRAND THEFT AUTO V", alias="Grand Theft Auto V"),
    ]
    result = await scanner.scan_multiple([listing(str(i), value) for i, value in enumerate(games)])
    assert scanner.price_collector.collect_comparables.await_count == 1
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (1, 2)


@pytest.mark.asyncio

async def test_candidate_prices_are_detected_individually(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, mocks = cache_scanner
    candidates = [listing(str(price), game(), price) for price in (5.0, 10.0, 14.0)]
    result = await scanner.scan_multiple(candidates)
    assert [call.args[0] for call in mocks["detector"].detect.call_args_list] == candidates
    assert [opportunity.listing_price for opportunity in result.opportunities] == [5.0, 10.0, 14.0]
    assert len({id(call.args[1]) for call in mocks["detector"].detect.call_args_list}) == 1


@pytest.mark.asyncio

async def test_separate_batch_scans_do_not_share_cache(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, _ = cache_scanner
    candidates = [listing("one", game()), listing("two", game())]
    first = await scanner.scan_multiple(candidates)
    second = await scanner.scan_multiple(candidates)
    assert scanner.price_collector.collect_comparables.await_count == 2
    assert (first.comparable_cache_misses, first.comparable_cache_hits) == (1, 1)
    assert (second.comparable_cache_misses, second.comparable_cache_hits) == (1, 1)


@pytest.mark.asyncio

async def test_separate_single_scans_do_not_share_cache(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, _ = cache_scanner
    candidate = listing("one", game())
    assert await scanner.scan_listing(candidate) is not None
    assert await scanner.scan_listing(candidate) is not None
    assert scanner.price_collector.collect_comparables.await_count == 2


@pytest.mark.asyncio

async def test_failed_valuation_is_reused_with_each_listing_id(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, mocks = cache_scanner
    scanner.price_collector.collect_comparables.side_effect = RuntimeError("collector unavailable")
    candidates = [listing(str(index), game()) for index in range(3)]
    result = await scanner.scan_multiple(candidates)
    assert scanner.price_collector.collect_comparables.await_count == 1
    assert mocks["builder"].build.call_count == 0
    assert [failure.listing_id for failure in result.failures] == ["0", "1", "2"]
    assert all(failure.stage == PipelineStage.PRICE_COLLECTION for failure in result.failures)
    assert all(failure.error_message == "collector unavailable" for failure in result.failures)
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (1, 2)


@pytest.mark.asyncio

async def test_failure_for_one_game_does_not_contaminate_another(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, mocks = cache_scanner
    scanner.price_collector.collect_comparables.side_effect = [
        RuntimeError("GTA failed"),
        [comparable("comp", game("Red Dead Redemption 2"), 20.0)],
    ]
    result = await scanner.scan_multiple(
        [listing("gta", game()), listing("rdr", game("Red Dead Redemption 2"))]
    )
    assert result.failed == 1
    assert result.successful == 1
    assert mocks["detector"].detect.call_count == 1
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (2, 0)


@pytest.mark.asyncio

async def test_empty_list_has_zero_cache_metrics(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, _ = cache_scanner
    result = await scanner.scan_multiple([])
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (0, 0)


@pytest.mark.asyncio

async def test_mixed_scenario_has_three_unique_valuations(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, mocks = cache_scanner
    candidates = (
        [listing(f"gta-ps4-{i}", game()) for i in range(6)]
        + [listing(f"rdr-{i}", game("Red Dead Redemption 2")) for i in range(2)]
        + [listing(f"gta-ps5-{i}", game(platform=Platform.PS5)) for i in range(2)]
    )
    result = await scanner.scan_multiple(candidates)
    assert mocks["collector"].collect_comparables.await_count == 3
    assert scanner.price_collector.collect_comparables.await_count == 3
    assert mocks["estimator"].estimate.call_count == 10
    assert mocks["detector"].detect.call_count == 10
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (3, 7)
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (3, 7)


@pytest.mark.asyncio
async def test_each_candidate_excludes_only_itself_from_cached_comparables(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, mocks = cache_scanner
    detected_game = game()
    candidates = [listing("A", detected_game), listing("B", detected_game)]
    market = [
        comparable("A", detected_game, 10.0),
        comparable("B", detected_game, 12.0),
        comparable("C", detected_game, 14.0),
        comparable("D", detected_game, 16.0),
    ]
    mocks["collector"].collect_comparables.return_value = market

    result = await scanner.scan_multiple(candidates)

    assert mocks["collector"].collect_comparables.await_count == 1
    assert [item.listing_id for item in mocks["builder"].build.call_args_list[0].args[0]] == [
        "B",
        "C",
        "D",
    ]
    assert [item.listing_id for item in mocks["builder"].build.call_args_list[1].args[0]] == [
        "A",
        "C",
        "D",
    ]
    assert mocks["estimator"].estimate.call_count == 2
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (1, 1)


@pytest.mark.asyncio
async def test_absent_candidate_and_empty_comparable_ids_are_preserved(
    cache_scanner: tuple[DefaultOpportunityScanner, dict[str, Mock]],
) -> None:
    scanner, mocks = cache_scanner
    detected_game = game()
    market = [
        comparable("", detected_game, 10.0),
        comparable("A", detected_game, 12.0),
        comparable("B", detected_game, 14.0),
        comparable("C", detected_game, 16.0),
    ]
    mocks["collector"].collect_comparables.return_value = market

    await scanner.scan_listing(listing("E", detected_game))

    assert mocks["builder"].build.call_args.args[0] == market
