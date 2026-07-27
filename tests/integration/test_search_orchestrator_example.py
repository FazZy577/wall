"""Smoke test for the deterministic offline search orchestrator example."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_search_orchestrator_example_runs_to_completion() -> None:
    """The documented offline pipeline is executable without network access."""
    project_root = Path(__file__).parents[2]
    example = project_root / "examples" / "search_orchestrator_example.py"

    completed = subprocess.run(
        [sys.executable, str(example)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "SEARCH ORCHESTRATION REPORT" in completed.stdout
    assert "Queries:" in completed.stdout
    assert "Individual opportunities:" in completed.stdout
    assert "Lot results:" in completed.stdout
