# Opportunity Scanner

**Module**: `domain.interfaces.opportunity_scanner`  
**Implementation**: `infrastructure.scanners.default_opportunity_scanner`

## Overview

The Opportunity Scanner is a **pure orchestrator** that coordinates the complete arbitrage detection pipeline. It contains **NO business logic** — only coordination.

## Candidate listings versus comparable listings

`CandidateListing` answers: **What listing are we considering buying?** It can
represent one game, a multi-game lot, or an ambiguous listing, and it has no
required single platform. The scanner creates `ListingText` from its title and
description; each returned `DetectedGame` owns its platform.

`ComparableListing` answers: **What individual accepted listings do we use to
estimate one game's market value?** These objects are produced by
`PriceCollector` and are the only listing objects passed to
`PriceDatasetBuilder`.

```text
CandidateListing (lot priced at 40 EUR)
        |
        +-- detects GTA V
        |       +-- PriceCollector
        |              +-- ComparableListing 12 EUR
        |              +-- ComparableListing 15 EUR
        |              +-- ComparableListing 18 EUR
        |
        +-- Arbitrage detector compares:
                candidate price 40 EUR
                against the game valuation
```

The candidate is never a market observation and cannot enter the price dataset.

## Execution-scoped valuation reuse (P1.1)

Previously, `scan_multiple()` ran the complete market valuation pipeline once per
candidate. This created an N+1 pattern: 100 candidate listings for five repeated
game identities could trigger up to 100 collections and valuations.

Each invocation of `scan_multiple()` now creates a private in-memory context. A
game identity is its normalized canonical name (`strip`, `casefold`, collapsed
whitespace) plus `Platform.value`. Aliases that resolve to the same canonical
name and platform share a valuation; the same name on PS4 and PS5 does not.

The cached outcome covers `PriceCollector`, `PriceDatasetBuilder`, initial
statistics, `OutlierRemoval`, recalculated statistics, and
`MarketPriceEstimator`. It stores the resulting `MarketPriceEstimate`, or the
original stage/reason/error details if valuation fails. A cached failure still
produces a separate `FailureInfo` with the correct candidate `listing_id`.

`ArbitrageOpportunity`, recommendation, candidate price, and opportunity score
are never cached. `ArbitrageOpportunityDetector` continues to run for every
processable candidate, so candidates sharing a market estimate can receive
different profitability metrics and recommendations.

The context exists only for one call. It is not an instance attribute, global
cache, persistent cache, or TTL cache. Separate calls to `scan_multiple()` and
every call to `scan_listing()` perform fresh valuations. `ScanResult` exposes
`valuation_cache_misses` (unique valuations attempted) and
`valuation_cache_hits` (later successful or failed outcomes reused).

After P1.1, 100 candidates covering five unique canonical-name/platform
identities require five valuations rather than up to 100.

## Critical Design Principle

⚠️ **This module does NOT contain:**
- Business rules
- Decision logic
- Thresholds or constants
- Formulas or calculations
- Data filtering rules
- Price computation
- Game detection logic
- Outlier detection heuristics

✅ **This module ONLY:**
- Calls components in the correct order
- Passes data between modules
- Handles errors gracefully
- Logs progress
- Returns results

## Pipeline Flow

```
Input: CandidateListing
  │
  ▼
┌─────────────────────────────────┐
│ 1. GameDetector                 │  Detect from ListingText title/description
│    Stage: GAME_DETECTION        │  If no game → skip listing
└──────────────┬──────────────────┘
               │ game: DetectedGame
               ▼
┌─────────────────────────────────┐
│ 2. PriceCollector               │  Collect comparable listings
│    Stage: PRICE_COLLECTION      │  from marketplace (async)
└──────────────┬──────────────────┘
               │ comparables: list[ComparableListing]
               ▼
┌─────────────────────────────────┐
│ 3. PriceDatasetBuilder          │  Build price dataset from
│    Stage: DATASET_BUILDING      │  comparable listings only
└──────────────┬──────────────────┘
               │ dataset: PriceDataset
               ▼
┌─────────────────────────────────┐
│ 4. PriceStatistics              │  Calculate initial statistics
│    Stage: STATISTICS            │  (mean, median, stddev, quartiles)
└──────────────┬──────────────────┘
               │ stats: PriceStatisticsResult
               ▼
┌─────────────────────────────────┐
│ 5. OutlierRemoval               │  Remove outliers (IQR method)
│    Stage: OUTLIER_REMOVAL       │
└──────────────┬──────────────────┘
               │ clean_dataset: PriceDataset
               ▼
┌─────────────────────────────────┐
│ 6. PriceStatistics (recalculate)│  Recalculate on clean data
│    Stage: STATISTICS_RECALC     │
└──────────────┬──────────────────┘
               │ clean_stats: PriceStatisticsResult
               ▼
┌─────────────────────────────────┐
│ 7. MarketPriceEstimator         │  Estimate market price
│    Stage: MARKET_ESTIMATION     │  (median strategy)
└──────────────┬──────────────────┘
               │ estimate: MarketPriceEstimate
               ▼
┌─────────────────────────────────┐
│ 8. ArbitrageOpportunityDetector │  Detect BUY/MAYBE/SKIP
│    Stage: OPPORTUNITY_DETECTION │
└──────────────┬──────────────────┘
               │
               ▼
Output: ArbitrageOpportunity
  (recommendation, profit, score, confidence, ...)
```

## Dependencies

The scanner receives **all** dependencies via constructor injection:

| Dependency | Interface | Purpose |
|---|---|---|
| `game_detector` | `IGameDetector` | Verifies game detection |
| `price_collector` | `IPriceCollector` | Collects comparable listings |
| `dataset_builder` | `IPriceDatasetBuilder` | Builds price datasets |
| `statistics` | `IPriceStatistics` | Calculates statistics |
| `outlier_removal` | `IOutlierRemoval` | Removes outliers |
| `market_estimator` | `IMarketPriceEstimator` | Estimates market price |
| `arbitrage_detector` | `IArbitrageOpportunityDetector` | Detects opportunities |

Optional parameters:
- `latitude` (float, default: 41.3874 — Barcelona)
- `longitude` (float, default: 2.1686 — Barcelona)
- `ranking_strategy` (RankingStrategy, default: OPPORTUNITY_SCORE)

## Ranking System

The scanner supports configurable ranking of opportunities. Results are always sorted by the configured strategy before being returned in `ScanResult.opportunities`.

### RankingStrategy

```python
class RankingStrategy(StrEnum):
    OPPORTUNITY_SCORE = "opportunity_score"   # Sort by opportunity_score descending (implemented)
    ABSOLUTE_PROFIT = "absolute_profit"       # Sort by estimated_profit descending (future)
    ROI = "roi"                               # Sort by roi_percentage descending (future)
    MARKET_DISCOUNT = "market_discount"       # Sort by market_discount_percentage descending (future)
    CUSTOM = "custom"                         # Custom ranking function (future)
```

Only `OPPORTUNITY_SCORE` is implemented initially — same pattern as `EstimationStrategy.MEDIAN`.
Unimplemented strategies fall back to `OPPORTUNITY_SCORE` with a warning.

### RankingResult

Provides ranked opportunities + summary statistics for dashboards:

```python
from domain.interfaces.opportunity_scanner import RankingResult, RankingStrategy

ranking = RankingResult.from_opportunities(
    result.opportunities,
    strategy=RankingStrategy.OPPORTUNITY_SCORE,
)

print(f"BUY: {ranking.buy_count}")          # 12
print(f"MAYBE: {ranking.maybe_count}")      # 5
print(f"SKIP: {ranking.skip_count}")        # 3
print(f"Best score: {ranking.best_score}")   # 92.0
print(f"Average score: {ranking.average_score}")  # 65.3

# Opportunities are already sorted by the strategy
for opp in ranking.ordered_opportunities:
    print(f"{opp.listing.title}: {opp.opportunity_score:.1f}/100")
```

| Field | Type | Description |
|---|---|---|
| `ordered_opportunities` | `list[ArbitrageOpportunity]` | Opportunities sorted by the ranking strategy |
| `buy_count` | `int` | Number of BUY recommendations |
| `maybe_count` | `int` | Number of MAYBE recommendations |
| `skip_count` | `int` | Number of SKIP recommendations |
| `best_score` | `float` | Highest opportunity score |
| `average_score` | `float` | Mean opportunity score |
| `created_at` | `datetime` | Timestamp when ranking was computed |

## Usage

### Single Listing

```python
from infrastructure.scanners.default_opportunity_scanner import (
    DefaultOpportunityScanner,
)

# Initialize with all dependencies (dependency injection)
scanner = DefaultOpportunityScanner(
    game_detector=game_detector,
    price_collector=price_collector,
    dataset_builder=dataset_builder,
    statistics=statistics,
    outlier_removal=outlier_removal,
    market_estimator=market_estimator,
    arbitrage_detector=arbitrage_detector,
)

# Scan a single listing
opportunity = scanner.scan_listing(listing)

if opportunity:
    print(f"{opportunity.recommendation}: {opportunity.opportunity_score:.1f}/100")
```

### Multiple Listings

```python
# Scan multiple listings
result = scanner.scan_multiple(listings)

print(f"Processed: {result.total_processed}")
print(f"Successful: {result.successful}")
print(f"Failed: {result.failed}")
print(f"Time: {result.processing_time:.2f}s")

# Opportunities sorted by score
for opp in sorted(result.opportunities, key=lambda x: x.opportunity_score, reverse=True):
    print(f"  {opp.listing.title}: €{opp.estimated_profit:.2f} profit ({opp.opportunity_score:.0f}/100)")
```

## Data Model

### ScanResult

**Attributes**:

| Field | Type | Description |
|---|---|---|
| `total_processed` | `int` | Total listings processed |
| `successful` | `int` | Successfully processed |
| `failed` | `int` | Failed to process |
| `opportunities` | `list[ArbitrageOpportunity]` | Detected opportunities |
| `failures` | `list[FailureInfo]` | Details of each failure |
| `processing_time` | `float` | Total processing time (seconds) |
| `created_at` | `datetime` | Scan timestamp (UTC) |
| `valuation_cache_hits` | `int` | Later candidates reusing a valuation outcome |
| `valuation_cache_misses` | `int` | Unique game valuations attempted |

### FailureInfo

| Field | Type | Description |
|---|---|---|
| `listing_id` | `str` | ID of the listing that failed |
| `stage` | `PipelineStage` | Pipeline stage where failure occurred |
| `reason` | `str` | Human-readable reason |
| `error_message` | `str \| None` | Technical error details |

### PipelineStage

```python
class PipelineStage(StrEnum):
    GAME_DETECTION = "game_detection"
    PRICE_COLLECTION = "price_collection"
    DATASET_BUILDING = "dataset_building"
    STATISTICS = "statistics"
    OUTLIER_REMOVAL = "outlier_removal"
    STATISTICS_RECALCULATION = "statistics_recalculation"
    MARKET_ESTIMATION = "market_estimation"
    OPPORTUNITY_DETECTION = "opportunity_detection"
```

## Error Handling

The scanner handles errors gracefully:

| Scenario | Behavior |
|---|---|
| **No detected game** | Skip listing, record `GAME_DETECTION` failure, continue |
| **Price collection fails** | Skip listing, record `PRICE_COLLECTION` failure, continue |
| **Empty dataset** | Skip listing, record `DATASET_BUILDING` failure, continue |
| **Any module throws** | Skip listing, record failure at the current stage, continue |
| **Empty input list** | Return `ScanResult` with all zeros |
| **Never aborts** | Processes ALL listings even if some fail |

## Logging

The scanner provides detailed logging:

```
INFO - Scanning listing 14/80
INFO - Game detected: Grand Theft Auto V
INFO - Collecting comparables...
INFO - Collected 25 comparable listings
INFO - Dataset built with 26 observations
INFO - Removing outliers...
INFO - Removed 2 outliers (7.7%)
INFO - Estimating market price...
INFO - Market price: EUR 22.00 (confidence: 0.80)
INFO - BUY detected (score: 85.3/100) in 0.84 s
INFO - Batch scan completed: 72 successful, 8 failed in 45.32 s
```

## Dependency Injection

All dependencies must be injected via constructor:

```python
scanner = DefaultOpportunityScanner(
    game_detector=FuzzyGameDetector(),
    price_collector=WallapopPriceCollector(client, game_detector, comparable_filter),
    dataset_builder=DefaultPriceDatasetBuilder(source="wallapop"),
    statistics=DefaultPriceStatistics(),
    outlier_removal=DefaultOutlierRemoval(),
    market_estimator=DefaultMarketPriceEstimator(),
    arbitrage_detector=DefaultArbitrageOpportunityDetector(),
)
```

The scanner does NOT instantiate any dependencies internally.

## Architecture

### Clean Architecture Compliance

```
┌─────────────────────────────────────────┐
│   Application Layer                     │
│   (Future: CLI, API, Web UI)            │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│   Domain Layer (Interfaces)             │
│   • IOpportunityScanner                 │
│   • ScanResult, FailureInfo             │
│   • PipelineStage                       │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│   Infrastructure Layer                  │
│   • DefaultOpportunityScanner           │
│     (Pure orchestrator — no logic)      │
└─────────────────────────────────────────┘
```

### Dependency Flow

The scanner depends on interfaces, not implementations:

```python
def __init__(
    self,
    game_detector: IGameDetector,                      # Interface
    price_collector: IPriceCollector,                   # Interface
    dataset_builder: IPriceDatasetBuilder,              # Interface
    statistics: IPriceStatistics,                        # Interface
    outlier_removal: IOutlierRemoval,                    # Interface
    market_estimator: IMarketPriceEstimator,             # Interface
    arbitrage_detector: IArbitrageOpportunityDetector,   # Interface
) -> None:
```

This allows swapping implementations without changing the scanner.

## Comparison with Other Modules

| Module | Contains Logic | Makes Decisions | Has Constants | Has Formulas |
|---|---|---|---|---|
| GameDetector | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| PriceCollector | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No |
| DatasetBuilder | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No |
| PriceStatistics | ✅ Yes | ❌ No | ❌ No | ✅ Yes |
| OutlierRemoval | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| MarketEstimator | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| ArbitrageDetector | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **OpportunityScanner** | ❌ **NO** | ❌ **NO** | ❌ **NO** | ❌ **NO** |

## Integration with Full System

The scanner is designed to be called by a higher-level orchestrator:

```
┌──────────────────────────────────────────┐
│  Full System Orchestrator (Future)       │
│                                          │
│  1. Scrape Wallapop                      │
│  2. Detect games in listings             │
│  3. Build CandidateListings              │
│  4. Call OpportunityScanner.scan_multiple│
│  5. Rank opportunities by score          │
│  6. Notify user / store results          │
└──────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│  OpportunityScanner                      │
│  (Coordinates pipeline for each listing) │
│                                          │
│  GameDetector → PriceCollector →         │
│  DatasetBuilder → Statistics →           │
│  OutlierRemoval → Statistics →           │
│  MarketEstimator → ArbitrageDetector     │
└──────────────────────────────────────────┘
```

## Testing

The scanner is tested with mocks (no real API calls, no Playwright):

```python
# Mock all dependencies
scanner = DefaultOpportunityScanner(
    game_detector=Mock(),
    price_collector=Mock(),
    dataset_builder=Mock(),
    statistics=Mock(),
    outlier_removal=Mock(),
    market_estimator=Mock(),
    arbitrage_detector=Mock(),
)
# Mock async runner for sync tests
scanner._run_async = Mock(return_value=[...])

# Test orchestration
result = scanner.scan_listing(listing)
```

Tests verify:
- Complete pipeline execution in correct order
- Game detection skip (no game → return None)
- Price collection failure handling
- Empty dataset handling
- Module errors at each pipeline stage
- Continuation after individual failures
- Mixed success/failure scenarios
- ScanResult field correctness
- PipelineStage tracking in FailureInfo

## Related Documentation

- [Game Detector](GAME_DETECTOR.md) — Detects games from listing text
- [Price Collector](PRICE_COLLECTOR.md) — Collects comparable listings
- [Price Dataset Builder](PRICE_DATASET_BUILDER.md) — Builds price datasets
- [Price Statistics](PRICE_STATISTICS.md) — Calculates statistics
- [Outlier Removal](OUTLIER_REMOVAL.md) — Removes price outliers
- [Market Price Estimator](MARKET_PRICE_ESTIMATOR.md) — Estimates market prices
- [Arbitrage Opportunity Detector](ARBITRAGE_OPPORTUNITY.md) — Makes BUY/MAYBE/SKIP decisions
- [Architecture](ARCHITECTURE.md) — Overall system design
