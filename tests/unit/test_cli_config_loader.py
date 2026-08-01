"""Tests for strict TOML configuration loading."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from presentation.cli.config import AppConfig
from presentation.cli.config_loader import (
    AppConfigLoadError,
    load_app_config,
)

VALID_TOML = """
[wallapop]
headless = true
timeout_ms = 30000
max_pages = 1
request_delay = 1.0

[location]
latitude = 40.4168
longitude = -3.7038

[search]
strategy = "canonical_only"
max_queries = 10
max_results_per_query = 20

[[search.targets]]
canonical_name = "Grand Theft Auto V"
platform = "PS4"

[economics]
selling_fee_rate = "0.10"
safety_buffer_rate = "0.05"
individual_min_net_profit_margin_percent = "25.0"
individual_min_confidence_score = 0.50

[[economics.currencies]]
currency = "EUR"
quick_sale_discount_per_item = "1.50"
fixed_selling_cost_per_item = "0.75"
acquisition_overhead = "2.00"
individual_min_net_profit = "10.00"
lot_min_net_profit = "15.00"

[output]
terminal = true
json_path = "reports/scan.json"
overwrite = false

[safety]
max_targets = 10
"""


def _write_config(path: Path, contents: str = VALID_TOML) -> Path:
    path.write_text(contents, encoding="utf-8")
    return path


def test_load_valid_toml_returns_immutable_app_config(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "config.toml")

    config = load_app_config(config_path)

    assert isinstance(config, AppConfig)
    assert config.search.targets[0].canonical_name == "Grand Theft Auto V"
    assert config.economics.currencies[0].currency == "EUR"
    assert config.wallapop.timeout_ms == 30_000


def test_loader_resolves_json_relative_to_config(tmp_path: Path) -> None:
    (tmp_path / "settings").mkdir()
    config_path = _write_config(tmp_path / "settings" / "config.toml")

    config = load_app_config(config_path)

    assert config.output.json_path == (tmp_path / "settings/reports/scan.json").resolve()
    assert not config.output.json_path.exists()  # type: ignore[union-attr]
    assert not (tmp_path / "settings/reports").exists()


def test_loader_preserves_absolute_json_path_without_writing(tmp_path: Path) -> None:
    output_path = (tmp_path / "absolute.json").resolve()
    contents = VALID_TOML.replace(
        'json_path = "reports/scan.json"',
        f"json_path = '{output_path}'",
    )
    config_path = _write_config(tmp_path / "config.toml", contents)

    config = load_app_config(config_path)

    assert config.output.json_path == output_path
    assert not output_path.exists()


def test_loader_accepts_omitted_optional_output_table(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "config.toml",
        VALID_TOML.replace(
            '\n[output]\nterminal = true\njson_path = "reports/scan.json"\noverwrite = false\n',
            "",
        ),
    )

    config = load_app_config(config_path)

    assert config.output.terminal is True
    assert config.output.json_path is None
    assert config.output.overwrite is False


def test_loader_reads_repository_example_without_operational_side_effects() -> None:
    example_path = Path(__file__).parents[2] / "config.example.toml"

    config = load_app_config(example_path)

    assert config.search.max_queries == 10
    assert config.search.targets[0].platform.value == "PS4"
    assert config.output.json_path == (example_path.parent / "reports/scan.json").resolve()
    assert not config.output.json_path.exists()  # type: ignore[union-attr]


@pytest.mark.parametrize("path", ["config.toml", "", None, 1, True, object()])
def test_loader_accepts_only_pathlib_path(path: object) -> None:
    with pytest.raises(TypeError, match="path must be pathlib.Path"):
        load_app_config(path)  # type: ignore[arg-type]


def test_loader_missing_file_uses_one_public_error_and_preserves_cause(
    tmp_path: Path,
) -> None:
    with pytest.raises(AppConfigLoadError, match="not found") as raised:
        load_app_config(tmp_path / "missing.toml")

    assert isinstance(raised.value, ValueError)
    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_loader_directory_has_public_read_error(tmp_path: Path) -> None:
    with pytest.raises(AppConfigLoadError, match="Unable to read") as raised:
        load_app_config(tmp_path)
    assert isinstance(raised.value.__cause__, OSError)


def test_loader_malformed_toml_has_public_parse_error(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "broken.toml", "[wallapop\nheadless = true")

    with pytest.raises(AppConfigLoadError, match="Invalid TOML") as raised:
        load_app_config(config_path)
    assert raised.value.__cause__ is not None


def test_loader_invalid_utf8_has_public_parse_error(tmp_path: Path) -> None:
    config_path = tmp_path / "broken.toml"
    config_path.write_bytes(b"[wallapop]\nheadless = \xff")

    with pytest.raises(AppConfigLoadError, match="Invalid TOML") as raised:
        load_app_config(config_path)
    assert isinstance(raised.value.__cause__, UnicodeDecodeError)


def test_loader_invalid_values_have_public_validation_error_without_raw_values(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path / "invalid.toml",
        VALID_TOML.replace('timeout_ms = 30000', 'timeout_ms = 0').replace(
            'max_targets = 10', 'max_targets = 0'
        ),
    )

    with pytest.raises(AppConfigLoadError, match="timeout_ms") as raised:
        load_app_config(config_path)

    assert isinstance(raised.value.__cause__, ValidationError)
    assert "30000" not in str(raised.value)


def test_loader_rejects_unknown_toml_fields(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "unknown.toml",
        VALID_TOML + '\n[wallapop.extra]\nsecret = "do-not-display"\n',
    )

    with pytest.raises(AppConfigLoadError, match="extra"):
        load_app_config(config_path)


def test_loader_rejects_non_string_decimal_values_from_toml(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "numeric-decimal.toml",
        VALID_TOML.replace('selling_fee_rate = "0.10"', "selling_fee_rate = 0.10"),
    )

    with pytest.raises(AppConfigLoadError, match="selling_fee_rate"):
        load_app_config(config_path)


def test_loader_does_not_use_environment_substitution(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "environment.toml",
        VALID_TOML.replace(
            'json_path = "reports/scan.json"',
            'json_path = "$CONFIG_OUTPUT/scan.json"',
        ),
    )

    config = load_app_config(config_path)

    assert config.output.json_path == (
        tmp_path / "$CONFIG_OUTPUT/scan.json"
    ).resolve()
