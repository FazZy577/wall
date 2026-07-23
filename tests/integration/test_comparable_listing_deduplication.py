"""Offline integration coverage for canonical comparable deduplication."""

from decimal import Decimal

from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.interfaces.market_price_estimator import ReasonCode
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def _game() -> DetectedGame:
    return DetectedGame(
        "Grand Theft Auto V",
        "GTA V",
        Platform.PS4,
        1.0,
        DetectionMethod.ALIAS_MATCH,
    )


def _comparable(identifier: str, price: str) -> ComparableListing:
    return ComparableListing(
        listing_id=identifier,
        title="GTA V PS4",
        description="",
        price=Decimal(price),
        currency="EUR",
        detected_game=_game(),
        url=f"https://example.test/{identifier}",
    )


def test_duplicates_do_not_inflate_statistics_outliers_or_estimation() -> None:
    raw = [
        _comparable("A", "10"),
        _comparable("A", "10"),
        _comparable("A", "10"),
        _comparable("B", "30"),
    ]

    dataset = DefaultPriceDatasetBuilder().build(raw, "EUR")
    statistics = DefaultPriceStatistics().calculate(dataset)
    outliers = DefaultOutlierRemoval().remove_outliers(dataset, statistics)
    clean_statistics = DefaultPriceStatistics().calculate(outliers.clean_dataset)
    estimate = DefaultMarketPriceEstimator().estimate(
        outliers.clean_dataset,
        clean_statistics,
        outliers.removed_count,
    )

    assert [item.price for item in dataset.observations] == [
        Decimal("10"),
        Decimal("30"),
    ]
    assert dataset.sample_size == statistics.count == 2
    assert statistics.mean_price == Decimal("20")
    assert statistics.median_price == Decimal("20")
    assert outliers.removed_count == 0
    assert outliers.clean_dataset.sample_size == 2
    assert estimate.sample_size == 2
    assert estimate.estimated_price == Decimal("20")
    assert estimate.reason_code is ReasonCode.INSUFFICIENT_DATA
    assert [(item.listing_id, item.price) for item in raw] == [
        ("A", Decimal("10")),
        ("A", Decimal("10")),
        ("A", Decimal("10")),
        ("B", Decimal("30")),
    ]
