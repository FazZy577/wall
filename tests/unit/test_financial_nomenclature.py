"""P1.8 guards for canonical financial names and one source of truth."""

import ast
from dataclasses import asdict, fields
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotOpportunity, LotReasonCode
from domain.entities.resale_economics import (
    EconomicBreakdown,
    ResaleAbsoluteCosts,
    ResaleEconomicPolicy,
)
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    ReasonCode,
    Recommendation,
)
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    MarketPriceEstimate,
)
from domain.interfaces.market_price_estimator import (
    ReasonCode as EstimateReasonCode,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)

OLD_FINANCIAL_NAMES = {
    "estimated_profit",
    "profit_margin_percentage",
    "roi_percentage",
    "market_discount_percentage",
    "break_even_price",
    "total_market_value",
}


def _game() -> DetectedGame:
    return DetectedGame(
        "GTA V", "GTA V", Platform.PS4, 1.0, DetectionMethod.EXACT_MATCH
    )


def _candidate() -> CandidateListing:
    return CandidateListing("candidate", "GTA V", "", Decimal("10.0"), "EUR", "url")


def _breakdown() -> EconomicBreakdown:
    return ResaleEconomicPolicy(
        {"EUR": ResaleAbsoluteCosts(Decimal("3.0"), Decimal("1.0"), Decimal("2.0"))},
        Decimal("0.10"),
        Decimal("0.05"),
    ).calculate(
        [Decimal("20.0")], Decimal("10.0"), "EUR"
    )


def _opportunity() -> ArbitrageOpportunity:
    return ArbitrageOpportunity(
        listing=_candidate(),
        game=_game(),
        market_price=Decimal("20.0"),
        listing_price=Decimal("10.0"),
        confidence_score=0.8,
        confidence_level=ConfidenceLevel.HIGH,
        opportunity_score=42.0,
        recommendation=Recommendation.MAYBE,
        reason=ReasonCode.LOW_EXPECTED_PROFIT,
        created_at=datetime.now(UTC),
        economic_breakdown=_breakdown(),
    )


def test_opportunities_delegate_uniform_financial_api_to_breakdown() -> None:
    opportunity = _opportunity()
    estimate = MarketPriceEstimate(
            game=_game(),
            estimated_price=Decimal("20.0"),
            confidence_score=0.8,
            confidence_level=ConfidenceLevel.HIGH,
            strategy=EstimationStrategy.MEDIAN,
            sample_size=3,
            observations_removed=0,
            outlier_percentage=0.0,
            minimum_price=Decimal("18.0"),
            maximum_price=Decimal("22.0"),
            standard_deviation=Decimal("1.0"),
            iqr=Decimal("2.0"),
            coefficient_of_variation=0.05,
            currency="EUR",
            reason_code=EstimateReasonCode.NORMAL,
            created_at=datetime.now(UTC),
        )
    valuation = GameValuation.from_market_estimate(
        _game(),
        estimate,
        observations_removed=0,
    )
    lot = LotOpportunity.from_valuations(
        listing=_candidate(),
        game_valuations=[valuation],
        recommendation=Recommendation.MAYBE,
        reason=LotReasonCode.FAIR_VALUE_LOT,
        opportunity_score=42.0,
        economic_breakdown=_breakdown(),
    )

    names = (
        "reference_market_value",
        "expected_sale_revenue",
        "net_expected_proceeds",
        "net_profit",
        "net_profit_margin_percentage",
        "net_roi_percentage",
        "acquisition_discount_to_reference_market_percentage",
        "break_even_sale_revenue",
    )
    for result in (opportunity, lot):
        for name in names:
            assert getattr(result, name) == getattr(result.economic_breakdown, name)


def test_asdict_contains_only_nested_stored_financial_values() -> None:
    serialized = asdict(_opportunity())

    assert serialized["economic_breakdown"]["net_profit"] == Decimal("1.45")
    assert OLD_FINANCIAL_NAMES.isdisjoint(serialized)
    assert "net_profit" not in serialized


@pytest.mark.parametrize("old_name", sorted(OLD_FINANCIAL_NAMES))
def test_opportunity_constructor_rejects_old_financial_keywords(old_name: str) -> None:
    values = asdict(_opportunity())
    values["listing"] = _candidate()
    values["game"] = _game()
    values["confidence_level"] = ConfidenceLevel.HIGH
    values["recommendation"] = Recommendation.MAYBE
    values["reason"] = ReasonCode.LOW_EXPECTED_PROFIT
    values["economic_breakdown"] = _breakdown()
    values[old_name] = 999.0

    with pytest.raises(TypeError):
        ArbitrageOpportunity(**values)


@pytest.mark.parametrize("old_name", ["min_profit_eur", "min_margin_percent"])
def test_detector_constructor_rejects_old_threshold_keywords(old_name: str) -> None:
    with pytest.raises(TypeError):
        DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), **{old_name: 1.0}
        )


def test_zero_denominator_behavior_is_preserved() -> None:
    zero = ResaleEconomicPolicy.neutral().calculate([], Decimal("0.0"), "EUR")

    assert zero.net_profit_margin_percentage == 0.0
    assert zero.net_roi_percentage == 0.0
    assert zero.acquisition_discount_to_reference_market_percentage == 0.0


def test_dataclasses_do_not_store_derived_financial_copies() -> None:
    assert OLD_FINANCIAL_NAMES.isdisjoint(field.name for field in fields(ArbitrageOpportunity))
    assert OLD_FINANCIAL_NAMES.isdisjoint(field.name for field in fields(LotOpportunity))
    assert "net_profit" not in {field.name for field in fields(ArbitrageOpportunity)}
    assert "net_profit" not in {field.name for field in fields(LotOpportunity)}


def test_production_ast_contains_no_old_financial_identifiers() -> None:
    violations: list[str] = []
    root = Path(__file__).parents[2] / "src"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            identifier = None
            if isinstance(node, ast.Name):
                identifier = node.id
            elif isinstance(node, ast.Attribute):
                identifier = node.attr
            elif isinstance(node, ast.arg):
                identifier = node.arg
            if identifier in OLD_FINANCIAL_NAMES:
                violations.append(f"{path}:{node.lineno}:{identifier}")

    assert violations == []
