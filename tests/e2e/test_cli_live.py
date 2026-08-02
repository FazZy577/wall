"""Opt-in live smoke test for the installed operational CLI boundary."""

import os
from pathlib import Path

import pytest

from presentation.cli.main import main


@pytest.mark.live
@pytest.mark.e2e
def test_operational_cli_live_smoke(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Run one bounded real scan through the synchronous CLI entry point."""
    if os.environ.get("RUN_LIVE_WALLAPOP_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_WALLAPOP_TESTS=1 to run the live CLI smoke test")

    config_path = tmp_path / "live-cli.toml"
    config_path.write_text(
        """
[wallapop]
headless = true
timeout_ms = 15000
max_pages = 1
request_delay = 1.0

[location]
latitude = 40.4168
longitude = -3.7038

[search]
strategy = "canonical_only"
max_queries = 1
max_results_per_query = 1

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
overwrite = false

[safety]
max_targets = 1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        ["scan", "--config", str(config_path), "--confirm-live"]
    )
    captured = capsys.readouterr()

    assert exit_code in {0, 1}
    assert exit_code not in {2, 3, 4, 5, 6, 7, 70, 130}
    assert "SEARCH PLAN GENERATION" in captured.out
    assert "SEARCH EXECUTION" in captured.out
    assert "INDIVIDUAL OPPORTUNITIES" in captured.out
    assert "LOT OPPORTUNITIES" in captured.out
    assert "FAILURES" in captured.out
    assert "SUMMARY" in captured.out
    assert "Grand Theft Auto V PS4" in captured.out
    assert "Traceback" not in captured.err
    assert list(tmp_path.iterdir()) == [config_path]
