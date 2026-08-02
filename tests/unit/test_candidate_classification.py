"""Contract and invariant tests for candidate classification values."""

from dataclasses import FrozenInstanceError

import pytest

from domain.entities.candidate_classification import (
    CandidateClassification,
    CandidateClassificationReason,
    CandidateDisposition,
)
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform


def _game(
    name: str = "Grand Theft Auto V",
    platform: Platform = Platform.PS4,
) -> DetectedGame:
    return DetectedGame(
        canonical_name=name,
        matched_text=name,
        platform=platform,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def test_dispositions_have_stable_values() -> None:
    assert [item.value for item in CandidateDisposition] == [
        "eligible_individual",
        "eligible_lot",
        "ignored",
        "ambiguous",
    ]


def test_reasons_have_stable_values() -> None:
    assert [item.value for item in CandidateClassificationReason] == [
        "eligible_single_game",
        "eligible_multi_game_lot",
        "no_included_game",
        "unsupported_hardware",
        "accessory_or_controller",
        "ambiguous_multiplatform",
        "unsupported_edition",
        "contextual_reference_only",
    ]


@pytest.mark.parametrize(
    ("disposition", "reason", "games"),
    [
        (
            CandidateDisposition.ELIGIBLE_INDIVIDUAL,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
            (_game(),),
        ),
        (
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
            (_game(), _game("Red Dead Redemption 2")),
        ),
        (
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
            (_game(), _game("Red Dead Redemption 2"), _game("Ghost of Tsushima")),
        ),
        (
            CandidateDisposition.IGNORED,
            CandidateClassificationReason.UNSUPPORTED_HARDWARE,
            (),
        ),
        (
            CandidateDisposition.AMBIGUOUS,
            CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
            (),
        ),
    ],
)
def test_valid_classifications(
    disposition: CandidateDisposition,
    reason: CandidateClassificationReason,
    games: tuple[DetectedGame, ...],
) -> None:
    classification = CandidateClassification(disposition, reason, games)
    assert classification.included_games == games


def test_classification_is_frozen_and_preserves_order() -> None:
    games = (_game(), _game("Red Dead Redemption 2"))
    classification = CandidateClassification(
        CandidateDisposition.ELIGIBLE_LOT,
        CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
        games,
    )

    assert classification.included_games == games
    with pytest.raises(FrozenInstanceError):
        classification.reason = CandidateClassificationReason.UNSUPPORTED_EDITION  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [None, "eligible_individual", object()],
)
def test_invalid_disposition_is_rejected(value: object) -> None:
    with pytest.raises(TypeError, match="disposition"):
        CandidateClassification(value, CandidateClassificationReason.NO_INCLUDED_GAME, ())  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [None, "unsupported_hardware", object()])
def test_invalid_reason_is_rejected(value: object) -> None:
    with pytest.raises(TypeError, match="reason"):
        CandidateClassification(CandidateDisposition.IGNORED, value, ())  # type: ignore[arg-type]


def test_included_games_must_be_tuple() -> None:
    with pytest.raises(TypeError, match="included_games"):
        CandidateClassification(
            CandidateDisposition.ELIGIBLE_INDIVIDUAL,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
            [_game()],  # type: ignore[arg-type]
        )


def test_included_games_must_contain_detected_games() -> None:
    with pytest.raises(TypeError, match="DetectedGame"):
        CandidateClassification(
            CandidateDisposition.ELIGIBLE_INDIVIDUAL,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
            (object(),),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("disposition", "reason", "games"),
    [
        (
            CandidateDisposition.ELIGIBLE_INDIVIDUAL,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
            (),
        ),
        (
            CandidateDisposition.ELIGIBLE_INDIVIDUAL,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
            (_game(), _game("Red Dead Redemption 2")),
        ),
        (
            CandidateDisposition.ELIGIBLE_INDIVIDUAL,
            CandidateClassificationReason.UNSUPPORTED_EDITION,
            (_game(),),
        ),
        (
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
            (),
        ),
        (
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
            (_game(),),
        ),
        (
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
            (_game(), _game("Red Dead Redemption 2")),
        ),
        (
            CandidateDisposition.IGNORED,
            CandidateClassificationReason.NO_INCLUDED_GAME,
            (_game(),),
        ),
        (
            CandidateDisposition.IGNORED,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
            (),
        ),
        (
            CandidateDisposition.AMBIGUOUS,
            CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
            (_game(),),
        ),
        (
            CandidateDisposition.AMBIGUOUS,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
            (),
        ),
    ],
)
def test_semantically_invalid_combinations_are_rejected(
    disposition: CandidateDisposition,
    reason: CandidateClassificationReason,
    games: tuple[DetectedGame, ...],
) -> None:
    with pytest.raises(ValueError):
        CandidateClassification(disposition, reason, games)


def test_duplicate_game_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        CandidateClassification(
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
            (_game(), _game(" grand   theft auto v ")),
        )


def test_same_name_on_different_platforms_is_not_duplicate() -> None:
    classification = CandidateClassification(
        CandidateDisposition.ELIGIBLE_LOT,
        CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
        (_game(platform=Platform.PS4), _game(platform=Platform.PS5)),
    )
    assert len(classification.included_games) == 2


def test_classification_has_no_listing_or_free_text_fields() -> None:
    field_names = set(CandidateClassification.__dataclass_fields__)
    assert field_names == {"disposition", "reason", "included_games"}
    for name in ("listing_id", "raw_listing", "text", "description", "explanation"):
        assert not hasattr(CandidateClassification, name)
