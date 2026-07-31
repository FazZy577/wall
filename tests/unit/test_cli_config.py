"""Tests for strict immutable operational CLI configuration models."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from application.interfaces.candidate_search import SearchQuery
from application.interfaces.search_plan_generator import SearchPlanGenerationStrategy
from domain.entities.detected_game import Platform
from presentation.cli.config import (
    AppConfig,
    CurrencyEconomicsConfig,
    EconomicsConfig,
    LocationConfig,
    OutputConfig,
    SafetyConfig,
    SearchConfig,
    SearchTargetConfig,
    WallapopConfig,
)


def _target(
    name: str = "Grand Theft Auto V",
    platform: Platform | str = Platform.PS4,
) -> SearchTargetConfig:
    return SearchTargetConfig(canonical_name=name, platform=platform)


def _currency(currency: str = "EUR") -> CurrencyEconomicsConfig:
    return CurrencyEconomicsConfig(
        currency=currency,
        quick_sale_discount_per_item="1.50",
        fixed_selling_cost_per_item="0.75",
        acquisition_overhead="2.00",
        individual_min_net_profit="10.00",
        lot_min_net_profit="15.00",
    )


def _economics(
    currencies: object = None,
    **overrides: object,
) -> EconomicsConfig:
    values: dict[str, object] = {
        "selling_fee_rate": "0.10",
        "safety_buffer_rate": "0.05",
        "individual_min_net_profit_margin_percent": "25.0",
        "individual_min_confidence_score": 0.5,
        "currencies": [_currency()] if currencies is None else currencies,
    }
    values.update(overrides)
    return EconomicsConfig.model_validate(values)


def _search(
    targets: object = None,
    **overrides: object,
) -> SearchConfig:
    values: dict[str, object] = {
        "max_queries": 10,
        "max_results_per_query": 20,
        "targets": [_target()] if targets is None else targets,
    }
    values.update(overrides)
    return SearchConfig.model_validate(values)


def _app(**overrides: object) -> AppConfig:
    values: dict[str, object] = {
        "wallapop": WallapopConfig(),
        "location": LocationConfig(latitude=40.4168, longitude=-3.7038),
        "search": _search(),
        "economics": _economics(),
        "safety": SafetyConfig(max_targets=10),
    }
    values.update(overrides)
    return AppConfig.model_validate(values)


def test_valid_app_config_uses_expected_nested_models_and_output_default() -> None:
    config = _app()

    assert isinstance(config.wallapop, WallapopConfig)
    assert isinstance(config.location, LocationConfig)
    assert isinstance(config.search, SearchConfig)
    assert isinstance(config.economics, EconomicsConfig)
    assert config.output == OutputConfig()
    assert config.safety == SafetyConfig(max_targets=10)


@pytest.mark.parametrize(
    "model",
    [
        WallapopConfig(),
        LocationConfig(latitude=0, longitude=0),
        _target(),
        _search(),
        _currency(),
        _economics(),
        OutputConfig(),
        SafetyConfig(max_targets=1),
        _app(),
    ],
)
def test_all_models_are_frozen(model: object) -> None:
    with pytest.raises(ValidationError, match="frozen"):
        setattr(model, next(iter(type(model).model_fields)), object())


@pytest.mark.parametrize(
    "model_type,values",
    [
        (WallapopConfig, {"unexpected": True}),
        (LocationConfig, {"latitude": 0, "longitude": 0, "unexpected": True}),
        (
            SearchTargetConfig,
            {"canonical_name": "GTA V", "platform": "PS4", "unexpected": True},
        ),
        (
            SearchConfig,
            {
                "max_queries": 1,
                "max_results_per_query": 1,
                "targets": [_target()],
                "unexpected": True,
            },
        ),
        (
            CurrencyEconomicsConfig,
            {
                "currency": "EUR",
                "quick_sale_discount_per_item": "0",
                "fixed_selling_cost_per_item": "0",
                "acquisition_overhead": "0",
                "individual_min_net_profit": "0",
                "lot_min_net_profit": "0",
                "unexpected": True,
            },
        ),
        (
            EconomicsConfig,
            {
                "selling_fee_rate": "0",
                "safety_buffer_rate": "0",
                "individual_min_net_profit_margin_percent": "0",
                "individual_min_confidence_score": 0,
                "currencies": [_currency()],
                "unexpected": True,
            },
        ),
        (OutputConfig, {"unexpected": True}),
        (SafetyConfig, {"max_targets": 1, "unexpected": True}),
        (
            AppConfig,
            {
                "wallapop": WallapopConfig(),
                "location": LocationConfig(latitude=0, longitude=0),
                "search": _search(),
                "economics": _economics(),
                "safety": SafetyConfig(max_targets=1),
                "unexpected": True,
            },
        ),
    ],
)
def test_every_section_rejects_unknown_fields(
    model_type: type[object],
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        model_type(**values)


def test_target_and_currency_sequences_are_snapshots_with_stable_order() -> None:
    gta = _target("GTA V")
    rdr = _target("RDR2")
    targets = [gta, rdr, gta]
    eur = _currency("EUR")
    usd = _currency("USD")
    currencies = [eur, usd]

    search = _search(targets=targets)
    economics = _economics(currencies=currencies)
    targets.clear()
    currencies.reverse()

    assert search.targets == (gta, rdr, gta)
    assert economics.currencies == (eur, usd)
    assert isinstance(search.targets, tuple)
    assert isinstance(economics.currencies, tuple)


def test_wallapop_defaults_are_safe_cli_defaults() -> None:
    config = WallapopConfig()

    assert config.headless is True
    assert config.timeout_ms == 30_000
    assert config.max_pages == 1
    assert config.request_delay == 1.0


@pytest.mark.parametrize("value", [0, 1, "true", "false"])
def test_wallapop_headless_is_strict_bool(value: object) -> None:
    with pytest.raises(ValidationError):
        WallapopConfig(headless=value)


@pytest.mark.parametrize("value", [1, 30_000, 120_000])
def test_wallapop_timeout_accepts_defensive_range(value: int) -> None:
    assert WallapopConfig(timeout_ms=value).timeout_ms == value


@pytest.mark.parametrize("value", [0, -1, 120_001, True, 1.0, "30000"])
def test_wallapop_timeout_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValidationError):
        WallapopConfig(timeout_ms=value)


@pytest.mark.parametrize("value", [1, 3])
def test_wallapop_max_pages_accepts_bounds(value: int) -> None:
    assert WallapopConfig(max_pages=value).max_pages == value


@pytest.mark.parametrize("value", [0, 4, True, 1.0, "1"])
def test_wallapop_max_pages_rejects_out_of_range_or_non_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        WallapopConfig(max_pages=value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 0.0), (1, 1.0), (0.25, 0.25), (10, 10.0)],
)
def test_wallapop_request_delay_accepts_real_numbers(
    value: int | float,
    expected: float,
) -> None:
    config = WallapopConfig(request_delay=value)

    assert config.request_delay == expected
    assert isinstance(config.request_delay, float)


@pytest.mark.parametrize(
    "value",
    [-0.1, 10.1, float("nan"), float("inf"), float("-inf"), True, "1"],
)
def test_wallapop_request_delay_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValidationError):
        WallapopConfig(request_delay=value)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(-90, -180), (0, 0), (40.4168, -3.7038), (90, 180)],
)
def test_location_accepts_search_query_coordinates(
    latitude: int | float,
    longitude: int | float,
) -> None:
    location = LocationConfig(latitude=latitude, longitude=longitude)
    query = SearchQuery("GTA V", latitude, longitude, 1)

    assert location.latitude == float(query.latitude)
    assert location.longitude == float(query.longitude)
    assert isinstance(location.latitude, float)
    assert isinstance(location.longitude, float)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("latitude", -90.01),
        ("latitude", 90.01),
        ("latitude", float("nan")),
        ("latitude", float("inf")),
        ("latitude", True),
        ("longitude", -180.01),
        ("longitude", 180.01),
        ("longitude", float("-inf")),
        ("longitude", False),
    ],
)
def test_location_rejects_the_same_invalid_coordinates_as_search_query(
    field_name: str,
    value: object,
) -> None:
    values: dict[str, object] = {"latitude": 0, "longitude": 0}
    values[field_name] = value
    with pytest.raises(ValidationError):
        LocationConfig.model_validate(values)
    with pytest.raises((TypeError, ValueError)):
        SearchQuery(
            "GTA V",
            values["latitude"],  # type: ignore[arg-type]
            values["longitude"],  # type: ignore[arg-type]
            1,
        )


def test_search_target_strips_only_outer_name_whitespace() -> None:
    target = _target("  Pokémon:   Stadium 2!  ", Platform.SWITCH)

    assert target.canonical_name == "Pokémon:   Stadium 2!"


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_search_target_rejects_empty_name(value: str) -> None:
    with pytest.raises(ValidationError, match="canonical_name"):
        _target(value)


@pytest.mark.parametrize("value", [None, 1, True, object()])
def test_search_target_rejects_non_string_name(value: object) -> None:
    with pytest.raises(ValidationError, match="canonical_name"):
        SearchTargetConfig.model_validate(
            {"canonical_name": value, "platform": Platform.PS4}
        )


@pytest.mark.parametrize(
    "platform",
    [Platform.PS4, Platform.PS5, Platform.XBOX_ONE, Platform.XBOX_SERIES, Platform.SWITCH],
)
def test_search_target_accepts_all_known_platform_types(platform: Platform) -> None:
    assert _target(platform=platform).platform is platform
    assert _target(platform=platform.value).platform is platform


@pytest.mark.parametrize("value", [Platform.UNKNOWN, "Unknown"])
def test_search_target_rejects_unknown_platform(value: Platform | str) -> None:
    with pytest.raises(ValidationError, match="UNKNOWN"):
        _target(platform=value)


@pytest.mark.parametrize("value", ["play 4", "ps4", "PS 4", "Xbox", "SWITCH"])
def test_search_target_rejects_unknown_or_approximate_platform(value: str) -> None:
    with pytest.raises(ValidationError, match="platform"):
        _target(platform=value)


@pytest.mark.parametrize("value", [None, 1, True, object()])
def test_search_target_rejects_non_platform_types(value: object) -> None:
    with pytest.raises(ValidationError, match="platform"):
        SearchTargetConfig.model_validate(
            {"canonical_name": "GTA V", "platform": value}
        )


def test_search_defaults_to_canonical_only_and_accepts_exact_public_value() -> None:
    assert _search().strategy is SearchPlanGenerationStrategy.CANONICAL_ONLY
    assert (
        _search(
            strategy=SearchPlanGenerationStrategy.CANONICAL_ONLY
        ).strategy
        is SearchPlanGenerationStrategy.CANONICAL_ONLY
    )
    assert (
        _search(strategy="canonical_only").strategy
        is SearchPlanGenerationStrategy.CANONICAL_ONLY
    )


def test_search_builds_typed_target_snapshot_from_mapping_sequence() -> None:
    config = SearchConfig.model_validate(
        {
            "max_queries": 1,
            "max_results_per_query": 1,
            "targets": [{"canonical_name": "GTA V", "platform": "PS4"}],
        }
    )

    assert config.targets == (_target("GTA V", Platform.PS4),)


@pytest.mark.parametrize("value", ["aliases", "CANONICAL_ONLY", None, 1])
def test_search_rejects_unknown_strategy(value: object) -> None:
    with pytest.raises(ValidationError, match="strategy"):
        _search(strategy=value)


@pytest.mark.parametrize("field_name,valid_values", [("max_queries", [1, 20]), ("max_results_per_query", [1, 50])])
def test_search_limits_accept_exact_bounds(
    field_name: str,
    valid_values: list[int],
) -> None:
    for value in valid_values:
        assert getattr(_search(**{field_name: value}), field_name) == value


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("max_queries", 0),
        ("max_queries", 21),
        ("max_queries", True),
        ("max_results_per_query", 0),
        ("max_results_per_query", 51),
        ("max_results_per_query", 1.0),
    ],
)
def test_search_limits_reject_invalid_values(field_name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _search(**{field_name: value})


@pytest.mark.parametrize("targets", [[], (), "GTA V", [_target(), object()]])
def test_search_rejects_empty_or_invalid_target_sequences(targets: object) -> None:
    with pytest.raises(ValidationError, match="targets"):
        _search(targets=targets)


@pytest.mark.parametrize("currency", ["EUR", "USD", "GBP"])
def test_currency_economics_accepts_normalized_currency(currency: str) -> None:
    assert _currency(currency).currency == currency


@pytest.mark.parametrize(
    "currency",
    ["eur", "EU", "EURO", " EU", "EU ", "€€€", "ÉUR", "E1R"],
)
def test_currency_economics_rejects_noncanonical_currency(currency: str) -> None:
    with pytest.raises(ValidationError, match="currency"):
        _currency(currency)


def test_currency_economics_parses_string_amounts_exactly() -> None:
    config = _currency()

    assert config.quick_sale_discount_per_item == Decimal("1.50")
    assert config.fixed_selling_cost_per_item == Decimal("0.75")
    assert config.acquisition_overhead == Decimal("2.00")
    assert config.individual_min_net_profit == Decimal("10.00")
    assert config.lot_min_net_profit == Decimal("15.00")


@pytest.mark.parametrize("value", [0, 1, 1.5, True, Decimal("1"), None])
def test_currency_economics_rejects_non_string_amount_input(value: object) -> None:
    values = _currency().model_dump()
    values["quick_sale_discount_per_item"] = value
    with pytest.raises(ValidationError, match="string"):
        CurrencyEconomicsConfig.model_validate(values)


@pytest.mark.parametrize(
    "value",
    ["-0.01", "NaN", "Infinity", "-Infinity", "not-a-decimal", "", " "],
)
def test_currency_economics_rejects_negative_nonfinite_or_empty_amount(
    value: str,
) -> None:
    values = {
        "currency": "EUR",
        "quick_sale_discount_per_item": value,
        "fixed_selling_cost_per_item": "0",
        "acquisition_overhead": "0",
        "individual_min_net_profit": "0",
        "lot_min_net_profit": "0",
    }
    with pytest.raises(ValidationError):
        CurrencyEconomicsConfig.model_validate(values)


def test_currency_economics_accepts_zero_for_all_amounts() -> None:
    config = CurrencyEconomicsConfig(
        currency="EUR",
        quick_sale_discount_per_item="0",
        fixed_selling_cost_per_item="0",
        acquisition_overhead="0",
        individual_min_net_profit="0",
        lot_min_net_profit="0",
    )

    assert all(
        value == Decimal("0")
        for name, value in config.model_dump().items()
        if name != "currency"
    )


def test_economics_parses_rates_margin_and_preserves_currency_order() -> None:
    eur = _currency("EUR")
    usd = _currency("USD")
    config = _economics(currencies=[eur, usd])

    assert config.selling_fee_rate == Decimal("0.10")
    assert config.safety_buffer_rate == Decimal("0.05")
    assert config.individual_min_net_profit_margin_percent == Decimal("25.0")
    assert config.individual_min_confidence_score == 0.5
    assert config.currencies == (eur, usd)


def test_economics_builds_typed_currency_snapshot_from_mapping_sequence() -> None:
    values = _currency().model_dump(mode="json")
    config = _economics(currencies=[values])

    assert config.currencies == (_currency(),)


@pytest.mark.parametrize("value", [0, 0.1, True, Decimal("0.1"), None])
def test_economics_rejects_non_string_decimal_input(value: object) -> None:
    with pytest.raises(ValidationError, match="string"):
        _economics(selling_fee_rate=value)


@pytest.mark.parametrize("field_name", ["selling_fee_rate", "safety_buffer_rate"])
@pytest.mark.parametrize("value", ["-0.01", "1", "1.01", "NaN", "Infinity"])
def test_economics_rejects_rates_outside_productive_range(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        _economics(**{field_name: value})


def test_economics_rejects_combined_rates_that_make_policy_invalid() -> None:
    with pytest.raises(
        ValidationError,
        match=r"selling_fee_rate \+ safety_buffer_rate",
    ):
        _economics(selling_fee_rate="0.6", safety_buffer_rate="0.4")


@pytest.mark.parametrize("value", ["-0.01", "NaN", "Infinity"])
def test_economics_rejects_invalid_margin_percent(value: str) -> None:
    with pytest.raises(ValidationError):
        _economics(individual_min_net_profit_margin_percent=value)


@pytest.mark.parametrize("value", [0, 0.5, 1])
def test_economics_accepts_confidence_bounds(value: int | float) -> None:
    config = _economics(individual_min_confidence_score=value)

    assert config.individual_min_confidence_score == float(value)


@pytest.mark.parametrize(
    "value",
    [-0.01, 1.01, float("nan"), float("inf"), True, "0.5"],
)
def test_economics_rejects_invalid_confidence(value: object) -> None:
    with pytest.raises(ValidationError):
        _economics(individual_min_confidence_score=value)


@pytest.mark.parametrize("currencies", [[], (), "EUR", [_currency(), object()]])
def test_economics_rejects_empty_or_invalid_currency_sequences(
    currencies: object,
) -> None:
    with pytest.raises(ValidationError, match="currencies"):
        _economics(currencies=currencies)


def test_economics_rejects_duplicate_currency_codes() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        _economics(currencies=[_currency("EUR"), _currency("EUR")])


def test_economic_fields_have_no_neutral_defaults() -> None:
    assert all(
        EconomicsConfig.model_fields[name].is_required()
        for name in (
            "selling_fee_rate",
            "safety_buffer_rate",
            "individual_min_net_profit_margin_percent",
            "individual_min_confidence_score",
            "currencies",
        )
    )
    assert all(
        CurrencyEconomicsConfig.model_fields[name].is_required()
        for name in CurrencyEconomicsConfig.model_fields
    )


def test_output_defaults_and_path_conversion_do_not_touch_filesystem(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "missing" / "report.json"
    defaults = OutputConfig()
    from_string = OutputConfig(json_path=str(output_path))
    from_path = OutputConfig(json_path=output_path)

    assert defaults.terminal is True
    assert defaults.json_path is None
    assert defaults.overwrite is False
    assert from_string.json_path == output_path
    assert from_path.json_path is output_path
    assert not output_path.exists()
    assert not output_path.parent.exists()


@pytest.mark.parametrize("value", ["", " ", "\t", 1, True, object()])
def test_output_rejects_empty_or_invalid_path(value: object) -> None:
    with pytest.raises(ValidationError, match="json_path"):
        OutputConfig(json_path=value)


@pytest.mark.parametrize("field_name", ["terminal", "overwrite"])
@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_output_booleans_are_strict(field_name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        OutputConfig.model_validate({field_name: value})


@pytest.mark.parametrize("value", [1, 20])
def test_safety_accepts_defensive_bounds(value: int) -> None:
    assert SafetyConfig(max_targets=value).max_targets == value


@pytest.mark.parametrize("value", [0, -1, 21, True, 1.0, "1"])
def test_safety_rejects_invalid_max_targets(value: object) -> None:
    with pytest.raises(ValidationError):
        SafetyConfig(max_targets=value)


def test_app_accepts_targets_exactly_at_safety_limit() -> None:
    targets = [_target(f"Game {index}") for index in range(3)]
    config = _app(search=_search(targets=targets), safety=SafetyConfig(max_targets=3))

    assert len(config.search.targets) == config.safety.max_targets


def test_app_rejects_targets_above_safety_limit() -> None:
    targets = [_target(f"Game {index}") for index in range(3)]
    with pytest.raises(ValidationError, match="max_targets"):
        _app(search=_search(targets=targets), safety=SafetyConfig(max_targets=2))


def test_app_requires_at_least_one_enabled_output() -> None:
    json_output = OutputConfig(terminal=False, json_path="report.json")

    assert _app(output=json_output).output is json_output
    with pytest.raises(ValidationError, match="at least one output"):
        _app(output=OutputConfig(terminal=False, json_path=None))


def test_nested_configuration_is_immutable() -> None:
    config = _app()

    with pytest.raises(ValidationError, match="frozen"):
        config.search.targets[0].canonical_name = "RDR2"  # type: ignore[misc]
    with pytest.raises(TypeError):
        config.search.targets[0] = _target("RDR2")  # type: ignore[index]
