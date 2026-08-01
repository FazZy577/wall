"""Strict TOML loading for the future operational CLI."""

import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError as _ValidationError

from presentation.cli.config import AppConfig

__all__ = [
    "AppConfigLoadError",
    "load_app_config",
]


class AppConfigLoadError(ValueError):
    """Raised when an application configuration cannot be loaded or validated."""


def _resolve_output_path(
    raw_config: dict[str, Any],
    config_path: Path,
) -> dict[str, Any]:
    """Return a shallow copy with a relative JSON destination made absolute."""
    raw_output = raw_config.get("output")
    if not isinstance(raw_output, dict):
        return raw_config

    raw_json_path = raw_output.get("json_path")
    if not isinstance(raw_json_path, str) or not raw_json_path.strip():
        return raw_config

    json_path = Path(raw_json_path)
    if not json_path.is_absolute():
        json_path = config_path.parent / json_path
    resolved_output = dict(raw_output)
    resolved_output["json_path"] = json_path.resolve(strict=False)
    resolved_config = dict(raw_config)
    resolved_config["output"] = resolved_output
    return resolved_config


def _safe_validation_message(error: _ValidationError) -> str:
    """Format validation locations without including raw configuration values."""
    details: list[str] = []
    for issue in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in issue["loc"]) or "<root>"
        details.append(f"{location}: {issue['msg']}")
    return "; ".join(details) or "invalid configuration"


def load_app_config(path: Path) -> AppConfig:
    """Load, resolve, and validate one immutable :class:`AppConfig` snapshot.

    The loader performs no environment substitution, no filesystem writes, and
    no operational composition. Relative ``output.json_path`` values are
    resolved relative to the TOML file rather than the process working
    directory.
    """
    if not isinstance(path, Path):
        raise TypeError("path must be pathlib.Path")

    config_path = path
    try:
        config_path = path.resolve(strict=False)
        with config_path.open("rb") as config_file:
            raw_config = tomllib.load(config_file)
    except FileNotFoundError as error:
        raise AppConfigLoadError(
            f"Configuration file not found: {config_path}"
        ) from error
    except (IsADirectoryError, OSError) as error:
        raise AppConfigLoadError(
            f"Unable to read configuration file: {config_path}"
        ) from error
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise AppConfigLoadError(
            f"Invalid TOML configuration: {config_path}"
        ) from error

    if not isinstance(raw_config, dict):
        raise AppConfigLoadError(
            f"TOML configuration root must be a table: {config_path}"
        )

    try:
        resolved_config = _resolve_output_path(raw_config, config_path)
        return AppConfig.model_validate(resolved_config)
    except _ValidationError as error:
        details = _safe_validation_message(error)
        raise AppConfigLoadError(
            f"Invalid application configuration in {config_path}: {details}"
        ) from error
    except OSError as error:
        raise AppConfigLoadError(
            f"Unable to resolve configuration output path: {config_path}"
        ) from error
