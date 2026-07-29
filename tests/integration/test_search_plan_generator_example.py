"""Smoke test for the deterministic offline search-plan generator example."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_search_plan_generator_example_runs_to_completion() -> None:
    """The documented generator-to-orchestrator pipeline runs without network."""
    project_root = Path(__file__).parents[2]
    example = project_root / "examples" / "search_plan_generator_example.py"

    completed = subprocess.run(
        [sys.executable, str(example)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "SEARCH PLAN GENERATION REPORT" in completed.stdout
    assert "SEARCH ORCHESTRATION REPORT" in completed.stdout
    assert "Targets:\n- received: 3" in completed.stdout
    assert "Queries:\n- generated: 2" in completed.stdout
    assert "- duplicates removed: 1" in completed.stdout
    assert "Grand Theft Auto V PS4" in completed.stdout
    assert "Red Dead Redemption 2 PS4" in completed.stdout
    assert "Individual opportunities:" in completed.stdout
    assert "Traceback" not in completed.stdout
    assert "Traceback" not in completed.stderr
