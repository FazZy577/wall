"""Unit tests for RuleBasedCandidateEligibilityPolicy."""

import ast
import inspect
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import get_type_hints

import pytest

from domain.entities.candidate_classification import (
    CandidateClassification,
    CandidateClassificationReason,
    CandidateDisposition,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.interfaces.candidate_eligibility_policy import (
    ICandidateEligibilityPolicy,
)
from domain.interfaces.comparable_filter import ComparableFilterInput
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.filters.rule_based_comparable_filter import (
    RuleBasedComparableFilter,
)

UNSUPPORTED_VARIANT_CASES = (
    ("GTA V Premium Edition PS4", "Grand Theft Auto V"),
    ("GTA V Edición Premium PS4", "Grand Theft Auto V"),
    ("Red Dead Redemption 2 Special Edition PS4", "Red Dead Redemption 2"),
    ("Red Dead Redemption 2 Edición Especial PS4", "Red Dead Redemption 2"),
    ("GTA V Ultimate Edition PS4", "Grand Theft Auto V"),
    ("GTA V Deluxe Edition PS4", "Grand Theft Auto V"),
    ("GTA V Collector's Edition PS4", "Grand Theft Auto V"),
    ("GTA V Collector’s Edition PS4", "Grand Theft Auto V"),
    ("GTA V Collector Edition PS4", "Grand Theft Auto V"),
    ("GTA V Edición Coleccionista PS4", "Grand Theft Auto V"),
    ("GTA V Gold Edition PS4", "Grand Theft Auto V"),
    ("GTA V Complete Edition PS4", "Grand Theft Auto V"),
    ("GTA V Anniversary Edition PS4", "Grand Theft Auto V"),
    ("GTA V Limited Edition PS4", "Grand Theft Auto V"),
    ("GTA V Edición Limitada PS4", "Grand Theft Auto V"),
    ("GTA V Steelbook PS4", "Grand Theft Auto V"),
    ("GTA V caja metálica PS4", "Grand Theft Auto V"),
    ("GTA V edición metálica PS4", "Grand Theft Auto V"),
    ("GTA V GOTY PS4", "Grand Theft Auto V"),
    ("GTA V Game of the Year PS4", "Grand Theft Auto V"),
    ("GTA V PS4 incluye DLC", "Grand Theft Auto V"),
    ("GTA V PS4 con DLC", "Grand Theft Auto V"),
    ("GTA V PS4 DLCs", "Grand Theft Auto V"),
    ("GTA V PS4 season pass", "Grand Theft Auto V"),
    ("GTA V PS4 pase de temporada", "Grand Theft Auto V"),
    ("GTA V PS4 contenido descargable incluido", "Grand Theft Auto V"),
    ("GTA V PS4 códigos sin usar", "Grand Theft Auto V"),
    ("GTA V PS4 con extras", "Grand Theft Auto V"),
    ("GTA V PS4 contenido adicional", "Grand Theft Auto V"),
    ("GTA V PS4 expansión incluida", "Grand Theft Auto V"),
    ("GTA V PS4 sin mapa", "Grand Theft Auto V"),
    ("GTA V PS4 sin manual", "Grand Theft Auto V"),
    ("GTA V PS4 sin carátula", "Grand Theft Auto V"),
    ("GTA V PS4 solo disco", "Grand Theft Auto V"),
    ("GTA V PS4 disco suelto", "Grand Theft Auto V"),
    ("GTA V PS4 solo caja", "Grand Theft Auto V"),
    ("GTA V PS4 caja vacía", "Grand Theft Auto V"),
    ("GTA V PS4 sin disco", "Grand Theft Auto V"),
    ("GTA V PS4 caja y manual sin juego", "Grand Theft Auto V"),
)

SAFE_STANDARD_CASES = (
    ("Grand Theft Auto V PS4", "Grand Theft Auto V"),
    ("Red Dead Redemption 2 PS4", "Red Dead Redemption 2"),
    ("GTA V PS4 Edición estándar", "Grand Theft Auto V"),
    ("GTA V PS4 Standard Edition", "Grand Theft Auto V"),
    ("GTA V PS4 juego completo", "Grand Theft Auto V"),
    ("GTA V PS4 con caja", "Grand Theft Auto V"),
    ("GTA V PS4 buen estado", "Grand Theft Auto V"),
    ("GTA V PS4 usado como nuevo", "Grand Theft Auto V"),
    ("GTA V PS4 Premium condition", "Grand Theft Auto V"),
    ("GTA V PS4 especial para regalo", "Grand Theft Auto V"),
    ("GTA V PS4 última unidad", "Grand Theft Auto V"),
    ("GTA V PS4 deluxe estado", "Grand Theft Auto V"),
    ("GTA V PS4 no incluye DLC", "Grand Theft Auto V"),
    ("GTA V PS4 sin contenido adicional", "Grand Theft Auto V"),
    ("GTA V PS4 DLC no incluido", "Grand Theft Auto V"),
    ("GTA V PS4 DLC disponible por separado", "Grand Theft Auto V"),
)


def _listing(
    title: str,
    description: str = "",
    *,
    raw_listing: dict[str, object] | None = None,
) -> CandidateListing:
    return CandidateListing(
        listing_id="candidate-eligibility",
        title=title,
        description=description,
        price=Decimal("10"),
        currency="EUR",
        url="https://example.test/candidate-eligibility",
        raw_listing={} if raw_listing is None else raw_listing,
    )


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


@pytest.fixture
def policy() -> RuleBasedCandidateEligibilityPolicy:
    return RuleBasedCandidateEligibilityPolicy()


def _assert_classification(
    result: CandidateClassification,
    disposition: CandidateDisposition,
    reason: CandidateClassificationReason,
    games: tuple[DetectedGame, ...] = (),
) -> None:
    assert isinstance(result, CandidateClassification)
    assert result.disposition is disposition
    assert result.reason is reason
    assert result.included_games == games


class TestContract:
    def test_implements_port_with_exact_synchronous_signature(self) -> None:
        assert issubclass(
            RuleBasedCandidateEligibilityPolicy,
            ICandidateEligibilityPolicy,
        )
        assert not inspect.iscoroutinefunction(
            RuleBasedCandidateEligibilityPolicy.classify
        )
        hints = get_type_hints(RuleBasedCandidateEligibilityPolicy.classify)
        assert hints["listing"] is CandidateListing
        assert hints["detected_games"] == Sequence[DetectedGame]
        assert hints["return"] is CandidateClassification

    @pytest.mark.parametrize("value", [None, object(), "listing"])
    def test_rejects_invalid_listing(
        self,
        policy: RuleBasedCandidateEligibilityPolicy,
        value: object,
    ) -> None:
        with pytest.raises(TypeError, match="CandidateListing"):
            policy.classify(value, ())  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [None, object(), 1, "games", b"games", bytearray()])
    def test_rejects_invalid_detected_game_sequence(
        self,
        policy: RuleBasedCandidateEligibilityPolicy,
        value: object,
    ) -> None:
        with pytest.raises(TypeError, match="Sequence"):
            policy.classify(_listing("GTA V PS4"), value)  # type: ignore[arg-type]

    def test_rejects_invalid_sequence_element(
        self,
        policy: RuleBasedCandidateEligibilityPolicy,
    ) -> None:
        with pytest.raises(TypeError, match="DetectedGame"):
            policy.classify(_listing("GTA V PS4"), [_game(), object()])  # type: ignore[list-item]

    def test_does_not_mutate_inputs_or_access_raw_listing(
        self,
        policy: RuleBasedCandidateEligibilityPolicy,
    ) -> None:
        listing = _listing(
            "GTA V PS4",
            "Juego físico",
            raw_listing={"sentinel": object()},
        )
        games = [_game()]
        listing_snapshot = dict(vars(listing))
        game_snapshot = dict(vars(games[0]))

        result = policy.classify(listing, games)

        assert vars(listing) == listing_snapshot
        assert vars(games[0]) == game_snapshot
        assert games == [_game()]
        assert result.included_games[0] is games[0]

    def test_duplicate_game_identity_is_not_silently_deduplicated(
        self,
        policy: RuleBasedCandidateEligibilityPolicy,
    ) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            policy.classify(
                _listing("Lote GTA V PS4"),
                (_game(), _game(" grand   theft auto v ")),
            )


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("PS4 Negra + 3 Juegos + 1 mando", "Incluye Red Dead Redemption 2"),
        ("PlayStation 4 Pro Blanca", ""),
        ("Consola PS4 Pro", ""),
        ("PS4 Pro 1 TB", ""),
        ("PS4 Pro con mando y juegos", ""),
        ("PS4 Slim", ""),
        ("Consola PS4 Slim 1 TB con juegos", ""),
        ("Videoconsola PlayStation 4", ""),
        ("PS4 500 GB + GTA V", ""),
        ("Xbox One 500GB", ""),
        ("PS5 2TB con GTA V", ""),
        ("PS4 + juegos", ""),
        ("Pack de consola con juegos", ""),
    ],
)
@pytest.mark.parametrize("games", [(), (_game(),), (_game(), _game("Red Dead Redemption 2"))])
def test_hardware_is_ignored_regardless_of_preliminary_games(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
    description: str,
    games: tuple[DetectedGame, ...],
) -> None:
    result = policy.classify(_listing(title, description), games)
    _assert_classification(
        result,
        CandidateDisposition.IGNORED,
        CandidateClassificationReason.UNSUPPORTED_HARDWARE,
    )


def test_hardware_precedes_accessory_and_multiplatform(
    policy: RuleBasedCandidateEligibilityPolicy,
) -> None:
    result = policy.classify(
        _listing("PS4 Pro + mando + juegos PS5"),
        (_game(),),
    )
    _assert_classification(
        result,
        CandidateDisposition.IGNORED,
        CandidateClassificationReason.UNSUPPORTED_HARDWARE,
    )


@pytest.mark.parametrize(
    "title",
    [
        "Grand Theft Auto V PS4",
        "Juego PS4 Grand Theft Auto V",
        "RDR2 para PlayStation 4",
        "Disco PS4",
        "GRAND THEFT AUTO V ps4",
        "Juego físico: GTA V, para PlayStation 4",
    ],
)
def test_platform_mentions_without_hardware_signals_remain_games(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
) -> None:
    game = _game()
    result = policy.classify(_listing(title), (game,))
    _assert_classification(
        result,
        CandidateDisposition.ELIGIBLE_INDIVIDUAL,
        CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
        (game,),
    )


@pytest.mark.parametrize(
    ("title", "game_name"),
    [
        ("Pro Evolution Soccer 2018 PS4", "Pro Evolution Soccer 2018"),
        ("PS4 Pro Evolution Soccer 2018", "Pro Evolution Soccer 2018"),
        (
            "PlayStation 4 Pro Evolution Soccer 2019",
            "Pro Evolution Soccer 2019",
        ),
    ],
)
def test_pro_evolution_soccer_is_not_mistaken_for_console_pro(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
    game_name: str,
) -> None:
    game = _game(game_name)

    result = policy.classify(_listing(title), (game,))

    _assert_classification(
        result,
        CandidateDisposition.ELIGIBLE_INDIVIDUAL,
        CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
        (game,),
    )


@pytest.mark.parametrize(("title", "game_name"), UNSUPPORTED_VARIANT_CASES)
def test_unsupported_variants_are_ambiguous_without_included_games(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
    game_name: str,
) -> None:
    result = policy.classify(_listing(title), (_game(game_name),))

    _assert_classification(
        result,
        CandidateDisposition.AMBIGUOUS,
        CandidateClassificationReason.UNSUPPORTED_EDITION,
    )


@pytest.mark.parametrize(("title", "game_name"), SAFE_STANDARD_CASES)
def test_standard_and_contextually_similar_text_remains_eligible(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
    game_name: str,
) -> None:
    game = _game(game_name)
    result = policy.classify(_listing(title), (game,))

    _assert_classification(
        result,
        CandidateDisposition.ELIGIBLE_INDIVIDUAL,
        CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
        (game,),
    )


def test_hardware_and_multiplatform_keep_precedence_over_unsupported_edition(
    policy: RuleBasedCandidateEligibilityPolicy,
) -> None:
    game = _game()
    hardware = policy.classify(
        _listing("PS4 Pro Blanca + GTA V Premium Edition"),
        (game,),
    )
    multiplatform = policy.classify(
        _listing("GTA V PS4 y PS5 Premium Edition"),
        (game,),
    )
    accessory = policy.classify(
        _listing("Mando PS4 + GTA V Premium Edition"),
        (game,),
    )

    _assert_classification(
        hardware,
        CandidateDisposition.IGNORED,
        CandidateClassificationReason.UNSUPPORTED_HARDWARE,
    )
    _assert_classification(
        multiplatform,
        CandidateDisposition.AMBIGUOUS,
        CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
    )
    _assert_classification(
        accessory,
        CandidateDisposition.IGNORED,
        CandidateClassificationReason.ACCESSORY_OR_CONTROLLER,
    )


@pytest.mark.parametrize(
    "games",
    [(), (_game(),), (_game(), _game("Red Dead Redemption 2"))],
)
def test_unsupported_variant_precedes_base_game_count_routing(
    policy: RuleBasedCandidateEligibilityPolicy,
    games: tuple[DetectedGame, ...],
) -> None:
    result = policy.classify(_listing("GTA V Premium Edition PS4"), games)

    _assert_classification(
        result,
        CandidateDisposition.AMBIGUOUS,
        CandidateClassificationReason.UNSUPPORTED_EDITION,
    )


def test_unsupported_variant_in_description_is_rejected_symmetrically(
    policy: RuleBasedCandidateEligibilityPolicy,
) -> None:
    game = _game()
    candidate = policy.classify(
        _listing("GTA V PS4", "Incluye DLC y contenido adicional"),
        (game,),
    )
    comparable = RuleBasedComparableFilter().is_valid_comparable(
        game,
        ComparableFilterInput(
            title="GTA V PS4",
            description="Incluye DLC y contenido adicional",
        ),
    )

    _assert_classification(
        candidate,
        CandidateDisposition.AMBIGUOUS,
        CandidateClassificationReason.UNSUPPORTED_EDITION,
    )
    assert comparable is False


@pytest.mark.parametrize(("title", "game_name"), UNSUPPORTED_VARIANT_CASES)
def test_candidate_and_comparable_reject_unsupported_variants_symmetrically(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
    game_name: str,
) -> None:
    game = _game(game_name)
    candidate = policy.classify(_listing(title), (game,))
    comparable = RuleBasedComparableFilter().is_valid_comparable(
        game,
        ComparableFilterInput(title=title, description=""),
    )

    assert candidate.disposition is CandidateDisposition.AMBIGUOUS
    assert candidate.reason is CandidateClassificationReason.UNSUPPORTED_EDITION
    assert candidate.included_games == ()
    assert comparable is False


def test_unsupported_variant_classification_is_deterministic_and_non_mutating(
    policy: RuleBasedCandidateEligibilityPolicy,
) -> None:
    listing = _listing("GTA V Premium Edition PS4", "Incluye DLC")
    game = _game()
    listing_snapshot = dict(vars(listing))
    game_snapshot = dict(vars(game))

    first = policy.classify(listing, [game])
    second = policy.classify(listing, [game])

    assert first == second
    assert first.included_games == ()
    assert vars(listing) == listing_snapshot
    assert vars(game) == game_snapshot


@pytest.mark.parametrize(
    "title",
    [
        "Mando PS4 + GTA V",
        "DualShock 4 con juego",
        "GTA V PS4 con mando",
        "Pack juego y controlador",
        "Joystick PS4 con GTA V",
        "Volante PS4 con juego",
        "Auriculares PS4 con GTA V",
        "Headset PS4 con juego",
        "Cámara PS4 con juego",
        "Cable HDMI PS4",
        "Cargador para mando PS4",
    ],
)
@pytest.mark.parametrize("games", [(), (_game(),), (_game(), _game("Red Dead Redemption 2"))])
def test_accessories_are_ignored_regardless_of_preliminary_games(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
    games: tuple[DetectedGame, ...],
) -> None:
    result = policy.classify(_listing(title), games)
    _assert_classification(
        result,
        CandidateDisposition.IGNORED,
        CandidateClassificationReason.ACCESSORY_OR_CONTROLLER,
    )


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("GTA V PS4 sin mando", ""),
        ("GTA V PS4", "No incluye mando"),
        ("GTA V PS4", "Mando no incluido"),
        ("GTA V PS4", "Solo juego, sin accesorios"),
    ],
)
def test_negated_accessories_do_not_reject_game(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
    description: str,
) -> None:
    game = _game()
    result = policy.classify(_listing(title, description), (game,))
    _assert_classification(
        result,
        CandidateDisposition.ELIGIBLE_INDIVIDUAL,
        CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
        (game,),
    )


@pytest.mark.parametrize(
    "title",
    [
        "GTA V PS4 y PS5",
        "GTA V PS5 y PS4",
        "GTA V PS5 / PS4",
        "Juego para PS4 y Xbox One",
        "Xbox One y Xbox Series",
        "PS4, PS5 y Xbox Series",
    ],
)
@pytest.mark.parametrize("games", [(), (_game(),), (_game(), _game("Red Dead Redemption 2"))])
def test_multiple_platform_families_are_ambiguous(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
    games: tuple[DetectedGame, ...],
) -> None:
    result = policy.classify(_listing(title), games)
    _assert_classification(
        result,
        CandidateDisposition.AMBIGUOUS,
        CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
    )


@pytest.mark.parametrize(
    "title",
    [
        "GTA V PS4 PlayStation 4",
        "GTA V PS4",
        "GTA V Xbox Series X",
        "GTA V Nintendo Switch",
    ],
)
def test_one_platform_family_is_not_ambiguous(
    policy: RuleBasedCandidateEligibilityPolicy,
    title: str,
) -> None:
    game = _game()
    result = policy.classify(_listing(title), (game,))
    _assert_classification(
        result,
        CandidateDisposition.ELIGIBLE_INDIVIDUAL,
        CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
        (game,),
    )


def test_no_detected_game_is_ignored(
    policy: RuleBasedCandidateEligibilityPolicy,
) -> None:
    result = policy.classify(_listing("Juego PS4 desconocido"), ())
    _assert_classification(
        result,
        CandidateDisposition.IGNORED,
        CandidateClassificationReason.NO_INCLUDED_GAME,
    )


def test_one_game_is_individual_and_preserves_identity(
    policy: RuleBasedCandidateEligibilityPolicy,
) -> None:
    game = _game()
    result = policy.classify(_listing("Grand Theft Auto V PS4"), [game])
    _assert_classification(
        result,
        CandidateDisposition.ELIGIBLE_INDIVIDUAL,
        CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
        (game,),
    )
    assert result.included_games[0] is game


@pytest.mark.parametrize("count", [2, 3, 4])
def test_multiple_games_are_lot_in_original_order(
    policy: RuleBasedCandidateEligibilityPolicy,
    count: int,
) -> None:
    games = tuple(_game(f"Game {index}") for index in range(count))
    result = policy.classify(_listing("Lote de juegos PS4"), games)
    _assert_classification(
        result,
        CandidateDisposition.ELIGIBLE_LOT,
        CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
        games,
    )
    assert all(
        actual is expected
        for actual, expected in zip(result.included_games, games, strict=True)
    )


def test_same_input_is_deterministic(
    policy: RuleBasedCandidateEligibilityPolicy,
) -> None:
    listing = _listing("Lote GTA V y Red Dead Redemption 2 PS4")
    games = (_game(), _game("Red Dead Redemption 2"))
    assert policy.classify(listing, games) == policy.classify(listing, games)


def test_implementation_has_no_forbidden_dependencies_or_io() -> None:
    module_path = Path(
        "src/infrastructure/classifiers/rule_based_candidate_eligibility_policy.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(name.startswith("application") for name in imports)
    assert not any(name.startswith("presentation") for name in imports)
    assert not any(name.startswith("infrastructure") for name in imports)
    forbidden = (
        "wallapop",
        "playwright",
        "scanner",
        "raw_listing",
        "async ",
        "await ",
        "open(",
        "pathlib",
        "decimal",
        "economic",
    )
    assert all(token not in source.casefold() for token in forbidden)


def test_module_has_no_mutable_global_collections() -> None:
    module_path = Path(
        "src/infrastructure/classifiers/rule_based_candidate_eligibility_policy.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    mutable_nodes = (ast.List, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp)
    global_mutables = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and any(isinstance(child, mutable_nodes) for child in ast.walk(node))
    ]
    assert global_mutables == []
