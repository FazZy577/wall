"""Contract tests for the candidate eligibility policy port."""

import inspect
from collections.abc import Sequence
from decimal import Decimal
from typing import get_type_hints

from domain.entities.candidate_classification import (
    CandidateClassification,
    CandidateClassificationReason,
    CandidateDisposition,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.interfaces.candidate_eligibility_policy import ICandidateEligibilityPolicy


def _listing() -> CandidateListing:
    return CandidateListing(
        listing_id="candidate-policy",
        title="GTA V PS4",
        description="Juego físico",
        price=Decimal("10"),
        currency="EUR",
        url="https://example.test/candidate-policy",
        raw_listing={"marker": "original"},
    )


def _game() -> DetectedGame:
    return DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="GTA V",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


class _FakePolicy(ICandidateEligibilityPolicy):
    def classify(
        self,
        listing: CandidateListing,
        detected_games: Sequence[DetectedGame],
    ) -> CandidateClassification:
        assert listing.title
        return CandidateClassification(
            CandidateDisposition.ELIGIBLE_INDIVIDUAL,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
            (detected_games[0],),
        )


def test_port_exists_and_is_abstract() -> None:
    assert issubclass(ICandidateEligibilityPolicy, object)
    assert inspect.isabstract(ICandidateEligibilityPolicy)


def test_classify_signature_is_synchronous_and_typed() -> None:
    method = ICandidateEligibilityPolicy.classify
    assert not inspect.iscoroutinefunction(method)
    hints = get_type_hints(method)
    assert hints["listing"] is CandidateListing
    assert hints["detected_games"] == Sequence[DetectedGame]
    assert hints["return"] is CandidateClassification


def test_fake_policy_can_implement_the_contract() -> None:
    policy = _FakePolicy()
    classification = policy.classify(_listing(), (_game(),))
    assert isinstance(classification, CandidateClassification)
    assert classification.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL


def test_fake_policy_does_not_mutate_inputs() -> None:
    listing = _listing()
    games = (_game(),)
    raw_snapshot = dict(listing.raw_listing)
    policy = _FakePolicy()

    policy.classify(listing, games)

    assert listing.raw_listing == raw_snapshot
    assert games[0].canonical_name == "Grand Theft Auto V"


def test_contract_module_has_no_infrastructure_application_or_runtime_concerns() -> None:
    source = inspect.getsource(ICandidateEligibilityPolicy)
    module_source = inspect.getsource(__import__(
        "domain.interfaces.candidate_eligibility_policy",
        fromlist=["ICandidateEligibilityPolicy"],
    ))
    combined = f"{source}\n{module_source}".casefold()
    for forbidden in (
        "infrastructure",
        "application",
        "wallapop",
        "playwright",
        "asyncio",
        "regex",
    ):
        assert forbidden not in combined
