"""Strict immutable configuration models for the future operational CLI."""

import math
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from application.interfaces.search_plan_generator import SearchPlanGenerationStrategy
from domain.entities.detected_game import Platform


class _StrictFrozenConfigModel(BaseModel):
    """Shared validation policy for every CLI configuration section."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _parse_decimal_string(value: object, field_name: str | None) -> Decimal:
    """Parse one finite Decimal while rejecting non-string raw inputs."""
    field_name = field_name or "decimal value"
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be provided as a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError(f"{field_name} must be a valid decimal string") from error
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _validate_real_number(
    value: object,
    field_name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    """Validate and snapshot a bounded finite real number as float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a real number")
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    converted = float(value)
    if not minimum <= converted <= maximum:
        raise ValueError(
            f"{field_name} must be between {minimum:g} and {maximum:g}"
        )
    return converted


class WallapopConfig(_StrictFrozenConfigModel):
    """Operational limits for the future Wallapop client composition."""

    headless: bool = True
    timeout_ms: int = 30_000
    max_pages: int = 1
    request_delay: float = 1.0

    @field_validator("timeout_ms")
    @classmethod
    def _validate_timeout_ms(cls, value: int) -> int:
        if not 0 < value <= 120_000:
            raise ValueError("timeout_ms must be between 1 and 120000")
        return value

    @field_validator("max_pages")
    @classmethod
    def _validate_max_pages(cls, value: int) -> int:
        if not 1 <= value <= 3:
            raise ValueError("max_pages must be between 1 and 3")
        return value

    @field_validator("request_delay", mode="before")
    @classmethod
    def _validate_request_delay(cls, value: object) -> float:
        return _validate_real_number(
            value,
            "request_delay",
            minimum=0.0,
            maximum=10.0,
        )


class LocationConfig(_StrictFrozenConfigModel):
    """Geographic point used by generated marketplace searches."""

    latitude: float
    longitude: float

    @field_validator("latitude", mode="before")
    @classmethod
    def _validate_latitude(cls, value: object) -> float:
        return _validate_real_number(
            value,
            "latitude",
            minimum=-90.0,
            maximum=90.0,
        )

    @field_validator("longitude", mode="before")
    @classmethod
    def _validate_longitude(cls, value: object) -> float:
        return _validate_real_number(
            value,
            "longitude",
            minimum=-180.0,
            maximum=180.0,
        )


class SearchTargetConfig(_StrictFrozenConfigModel):
    """One explicit canonical game target requested by the operator."""

    canonical_name: str
    platform: Platform

    @field_validator("canonical_name")
    @classmethod
    def _validate_canonical_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("canonical_name must not be empty")
        return normalized

    @field_validator("platform", mode="before")
    @classmethod
    def _parse_platform(cls, value: object) -> Platform:
        if isinstance(value, Platform):
            platform = value
        elif isinstance(value, str):
            try:
                platform = Platform(value)
            except ValueError as error:
                raise ValueError("platform must be an exact Platform value") from error
        else:
            raise ValueError("platform must be Platform or an exact Platform value")
        if platform is Platform.UNKNOWN:
            raise ValueError("platform must not be UNKNOWN")
        return platform


class SearchConfig(_StrictFrozenConfigModel):
    """Deterministic search-plan generation configuration."""

    strategy: SearchPlanGenerationStrategy = SearchPlanGenerationStrategy.CANONICAL_ONLY
    max_queries: int
    max_results_per_query: int
    targets: tuple[SearchTargetConfig, ...]

    @field_validator("strategy", mode="before")
    @classmethod
    def _parse_strategy(cls, value: object) -> SearchPlanGenerationStrategy:
        if isinstance(value, SearchPlanGenerationStrategy):
            return value
        if isinstance(value, str):
            try:
                return SearchPlanGenerationStrategy(value)
            except ValueError as error:
                raise ValueError(
                    "strategy must be an exact SearchPlanGenerationStrategy value"
                ) from error
        raise ValueError(
            "strategy must be SearchPlanGenerationStrategy or its exact value"
        )

    @field_validator("max_queries")
    @classmethod
    def _validate_max_queries(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("max_queries must be between 1 and 20")
        return value

    @field_validator("max_results_per_query")
    @classmethod
    def _validate_max_results_per_query(cls, value: int) -> int:
        if not 1 <= value <= 50:
            raise ValueError("max_results_per_query must be between 1 and 50")
        return value

    @field_validator("targets", mode="before")
    @classmethod
    def _snapshot_targets(cls, value: object) -> tuple[Any, ...]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise ValueError("targets must be a sequence")
        return tuple(value)

    @field_validator("targets")
    @classmethod
    def _require_targets(
        cls,
        value: tuple[SearchTargetConfig, ...],
    ) -> tuple[SearchTargetConfig, ...]:
        if not value:
            raise ValueError("targets must contain at least one target")
        return value


class CurrencyEconomicsConfig(_StrictFrozenConfigModel):
    """Currency-specific absolute costs and profitability thresholds."""

    currency: str
    quick_sale_discount_per_item: Decimal
    fixed_selling_cost_per_item: Decimal
    acquisition_overhead: Decimal
    individual_min_net_profit: Decimal
    lot_min_net_profit: Decimal

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        if (
            len(value) != 3
            or not value.isascii()
            or not value.isalpha()
            or value != value.upper()
        ):
            raise ValueError(
                "currency must be a three-letter uppercase ASCII code"
            )
        return value

    @field_validator(
        "quick_sale_discount_per_item",
        "fixed_selling_cost_per_item",
        "acquisition_overhead",
        "individual_min_net_profit",
        "lot_min_net_profit",
        mode="before",
    )
    @classmethod
    def _parse_amount(cls, value: object, info: ValidationInfo) -> Decimal:
        return _parse_decimal_string(value, info.field_name)

    @field_validator(
        "quick_sale_discount_per_item",
        "fixed_selling_cost_per_item",
        "acquisition_overhead",
        "individual_min_net_profit",
        "lot_min_net_profit",
    )
    @classmethod
    def _require_non_negative_amount(
        cls,
        value: Decimal,
        info: ValidationInfo,
    ) -> Decimal:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value


class EconomicsConfig(_StrictFrozenConfigModel):
    """Global rates and per-currency operational economic configuration."""

    selling_fee_rate: Decimal
    safety_buffer_rate: Decimal
    individual_min_net_profit_margin_percent: Decimal
    individual_min_confidence_score: float
    currencies: tuple[CurrencyEconomicsConfig, ...]

    @field_validator(
        "selling_fee_rate",
        "safety_buffer_rate",
        "individual_min_net_profit_margin_percent",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object, info: ValidationInfo) -> Decimal:
        return _parse_decimal_string(value, info.field_name)

    @field_validator("selling_fee_rate", "safety_buffer_rate")
    @classmethod
    def _validate_rate(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        if not Decimal("0") <= value < Decimal("1"):
            raise ValueError(f"{info.field_name} must be at least 0 and less than 1")
        return value

    @field_validator("individual_min_net_profit_margin_percent")
    @classmethod
    def _validate_margin_percent(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError(
                "individual_min_net_profit_margin_percent must be non-negative"
            )
        return value

    @field_validator("individual_min_confidence_score", mode="before")
    @classmethod
    def _validate_confidence(cls, value: object) -> float:
        return _validate_real_number(
            value,
            "individual_min_confidence_score",
            minimum=0.0,
            maximum=1.0,
        )

    @field_validator("currencies", mode="before")
    @classmethod
    def _snapshot_currencies(cls, value: object) -> tuple[Any, ...]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise ValueError("currencies must be a sequence")
        return tuple(value)

    @field_validator("currencies")
    @classmethod
    def _validate_currencies(
        cls,
        value: tuple[CurrencyEconomicsConfig, ...],
    ) -> tuple[CurrencyEconomicsConfig, ...]:
        if not value:
            raise ValueError("currencies must contain at least one currency")
        currency_codes = [entry.currency for entry in value]
        if len(currency_codes) != len(set(currency_codes)):
            raise ValueError("currencies must not contain duplicate currency codes")
        return value

    @model_validator(mode="after")
    def _validate_combined_rates(self) -> Self:
        if self.selling_fee_rate + self.safety_buffer_rate >= Decimal("1"):
            raise ValueError(
                "selling_fee_rate + safety_buffer_rate must be less than 1"
            )
        return self


class OutputConfig(_StrictFrozenConfigModel):
    """Enabled report destinations without performing filesystem access."""

    terminal: bool = True
    json_path: Path | None = None
    overwrite: bool = False

    @field_validator("json_path", mode="before")
    @classmethod
    def _parse_json_path(cls, value: object) -> Path | None:
        if value is None or isinstance(value, Path):
            return value
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("json_path must not be empty")
            return Path(value)
        raise ValueError("json_path must be Path, string, or None")


class SafetyConfig(_StrictFrozenConfigModel):
    """Defensive bounds applied before operational execution."""

    max_targets: int

    @field_validator("max_targets")
    @classmethod
    def _validate_max_targets(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("max_targets must be between 1 and 20")
        return value


class AppConfig(_StrictFrozenConfigModel):
    """Complete immutable configuration snapshot for one future CLI run."""

    wallapop: WallapopConfig
    location: LocationConfig
    search: SearchConfig
    economics: EconomicsConfig
    output: OutputConfig = Field(default_factory=OutputConfig)
    safety: SafetyConfig

    @model_validator(mode="after")
    def _validate_operational_constraints(self) -> Self:
        if len(self.search.targets) > self.safety.max_targets:
            raise ValueError("search targets exceed safety.max_targets")
        if not self.output.terminal and self.output.json_path is None:
            raise ValueError(
                "at least one output must be enabled: terminal or json_path"
            )
        return self
