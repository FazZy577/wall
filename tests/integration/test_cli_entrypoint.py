"""Installed and module entry-point checks for the operational CLI."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
DIST_NAME = "wallapop-arbitrage"


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return environment


def _run(command: list[str], working_directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=working_directory,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )


def _uv_run(*arguments: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uv",
        "run",
        "--project",
        str(PROJECT_ROOT),
        *arguments,
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("argument", "expected_text"),
    (("--help", "scan"), ("--version", f"{DIST_NAME} 0.1.0")),
)
def test_module_entrypoint_works_without_pythonpath(
    argument: str,
    expected_text: str,
    tmp_path: Path,
) -> None:
    result = _run(
        _uv_run("python", "-m", "presentation.cli", argument),
        tmp_path,
    )

    assert result.returncode == 0
    assert expected_text in result.stdout
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.integration
def test_console_script_metadata_and_installed_help(tmp_path: Path) -> None:
    metadata_result = _run(
        _uv_run(
            "python",
            "-c",
            "from importlib.metadata import distribution; "
            "print(next(entry.value for entry in distribution('wallapop-arbitrage').entry_points "
            "if entry.group == 'console_scripts' and entry.name == 'wallapop-arbitrage'))",
        ),
        tmp_path,
    )
    assert metadata_result.returncode == 0
    assert metadata_result.stdout.strip() == "presentation.cli.main:main"

    result = _run(_uv_run(DIST_NAME, "--help"), tmp_path)

    assert result.returncode == 0
    assert "scan" in result.stdout
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.integration
def test_console_script_version_uses_installed_metadata(tmp_path: Path) -> None:
    result = _run(_uv_run(DIST_NAME, "--version"), tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == f"{DIST_NAME} 0.1.0"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.integration
def test_invalid_module_arguments_keep_argparse_exit_code_two(tmp_path: Path) -> None:
    result = _run(
        _uv_run("python", "-m", "presentation.cli", "scan"),
        tmp_path,
    )

    assert result.returncode == 2
    assert "--config" in result.stderr
    assert "--confirm-live" in result.stderr
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []
