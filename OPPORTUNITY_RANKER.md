# Opportunity Ranker

**Module**: `domain.interfaces.opportunity_ranker`  
**Implementation**: `infrastructure.rankers.default_opportunity_ranker`

## Overview

The Opportunity Ranker is a **pure sorting module** that ranks arbitrage opportunities by a configurable strategy. It contains **NO business logic** — only ordering and summarization.

## Responsibility

The ranker receives `list[ArbitrageOpportunity]` and returns them sorted from best to worst. Its ONLY responsibilities are:

- **Sort** opportunities by the configured strategy
- **Tie-break** deterministically when scores are equal
- **Apply** an optional limit
- **Summarize** the ranked list with statistics

It does NOT:
- Recalculate opportunity scores
- Change BUY/MAYBE/SKIP recommendations
- Estimate prices or profits
- Detect games or collect listings
- Contact any external API

## Why It's Separate from OpportunityScanner

The ranker is **not integrated** into the `OpportunityScanner` yet. This is intentional:

- The scanner coordinates the pipeline (game detection → price collection → ... → opportunity detection)
- The ranker is a **post-processing** step that orders the scanner's output
- Separation allows the ranker to be used independently (e.g., ranking cached opportunities)
- Integration will happen in a future phase

## Data Flow

```
list[ArbitrageOpportunity]
        │
        ▼
┌───────────────────┐
│ OpportunityRanker  │
│                    │
│ 1. Validate limit  │
│ 2. Sort by strategy│
│ 3. Tie-break       │
│ 4. Apply limit     │
│ 5. Summarize       │
└────────┬───────────┘
         │
         ▼
    RankingResult
    (ordered list + summary stats)
```

## Ranking Strategy

Only one strategy is implemented:

```python
class RankingStrategy(StrEnum):
    OPPORTUNITY_SCORE = "opportunity_score"
```

Future strategies (not yet implemented):
- `ABSOLUTE_PROFIT` — sort by `estimated_profit` descending
- `ROI` — sort by `roi_percentage` descending
- `MARKET_DISCOUNT` — sort by `market_discount_percentage` descending
- `CONFIDENCE` — sort by `confidence_score` descending
- `HYBRID` — weighted combination of multiple factors

Attempting to use an unimplemented strategy raises `UnsupportedRankingStrategyError`.

## Primary Sort

By `opportunity_score` descending:

```
92.5 → 88.2 → 73.0 → 41.7
```

## Tie-Breaking

When two opportunities have the same `opportunity_score`, the following criteria are applied in order:

| # | Criterion | Direction |
|---|---|---|
| 1 | `estimated_profit` | Descending (higher profit first) |
| 2 | `confidence_score` | Descending (more confident first) |
| 3 | `roi_percentage` | Descending (higher ROI first) |
| 4 | `listing.listing_id` | Ascending (stable, deterministic) |

Example:

```
Score 80.0, Profit €18.00  →  ranks FIRST
Score 80.0, Profit €10.00  →  ranks SECOND
```

## recommendation vs Ranking

The ranker does **NOT** alter `recommendation`. It preserves the original BUY/MAYBE/SKIP from the `ArbitrageOpportunityDetector`.

The ranking is purely by `opportunity_score` — a high score with a SKIP recommendation would still rank above a low score with BUY. This is intentional: the score encodes all relevant factors, and the recommendation is informational.

## Limit

| Value | Behavior |
|---|---|
| `None` | Return all opportunities |
| `3` | Return top 3 |
| `0` | Return empty list |
| `-1` | Raise `InvalidRankingLimitError` |

The limit is applied **after** sorting. Counts (BUY/MAYBE/SKIP) are computed over **all** received opportunities, not just the returned ones.

Example:

```python
# 100 received, limit=10
result = ranker.rank(opportunities, limit=10)
result.total_received  # 100
result.total_ranked    # 100
result.total_returned  # 10
result.buy_count       # 45 (counted over all 100)
```

## Usage

```python
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker
from domain.interfaces.opportunity_ranker import RankingStrategy

ranker = DefaultOpportunityRanker(strategy=RankingStrategy.OPPORTUNITY_SCORE)

# Full ranking
result = ranker.rank(opportunities)

# Top 10
top10 = ranker.rank(opportunities, limit=10)

# Summary
print(f"BUY: {result.buy_count}, Best: {result.best_score}")

# Human-readable output
print(result.explain())
```

## RankingResult

```python
@dataclass
class RankingResult:
    ordered_opportunities: list[ArbitrageOpportunity]  # Sorted (post-limit)
    strategy: RankingStrategy                           # Strategy used
    total_received: int                                 # Input size
    total_ranked: int                                   # = total_received
    total_returned: int                                 # After limit
    buy_count: int                                      # BUY in all received
    maybe_count: int                                    # MAYBE in all received
    skip_count: int                                     # SKIP in all received
    best_score: float | None                            # None if empty
    average_score: float | None                         # None if empty
    created_at: datetime                                # Ranking timestamp
```

For an empty input:
- `best_score = None` (not `0.0`)
- `average_score = None` (not `0.0`)
- All counts = `0`

## explain()

Returns a deterministic human-readable summary:

```
============================================================
OPPORTUNITY RANKING
============================================================

Strategy: OPPORTUNITY_SCORE

Total Received: 25
Total Returned: 10

Recommendations:
BUY: 7
MAYBE: 12
SKIP: 6

Best Score: 92.40
Average Score: 61.35

## TOP OPPORTUNITIES

1. Grand Theft Auto V PS4
   Score: 92.40
   Profit: EUR 25.00
   Recommendation: BUY

2. Red Dead Redemption 2 PS4
   Score: 89.10
   Profit: EUR 21.00
   Recommendation: BUY

============================================================
```

## Immutability

The ranker never modifies:
- The input list
- Any `ArbitrageOpportunity` object

It creates a new sorted list.

## Exceptions

| Exception | When |
|---|---|
| `InvalidRankingLimitError` | Limit is negative |
| `UnsupportedRankingStrategyError` | Strategy is not yet implemented |

## How to Add a Future Strategy

1. Add the value to `RankingStrategy` enum
2. Implement the sort logic in `DefaultOpportunityRanker._sort_key`
3. Update `_validate_strategy` to allow the new value
4. Add tests for the new strategy
5. Update this documentation

The API (`rank()` method signature) does NOT change. Only the internal sort key changes.

## Testing

Tests verify:
- Empty list handling
- Single opportunity
- Descending order by score
- Tie-breaking by profit, confidence, ROI, and listing_id
- Determinism (identical results on repeated calls)
- Immutability (original list and objects unchanged)
- All limit cases (None, 0, < total, > total, negative)
- Counts over all received (not just returned)
- best_score and average_score (including None for empty)
- explain() output correctness
- Exception messages

See `tests/unit/test_default_opportunity_ranker.py` for all test cases.

## Future Integration

When the ranker is integrated into `OpportunityScanner`:

```python
# Future code (not yet implemented):
scanner = DefaultOpportunityScanner(...)
result = await scanner.scan_multiple(listings)

ranker = DefaultOpportunityRanker()
ranking = ranker.rank(result.opportunities, limit=10)
print(ranking.explain())
```

The ranker is designed to be a drop-in post-processing step.

## Related Documentation

- [Opportunity Scanner](OPPORTUNITY_SCANNER.md) — Orchestrates the pipeline
- [Arbitrage Opportunity Detector](ARBITRAGE_OPPORTUNITY.md) — Creates `ArbitrageOpportunity` objects
- [Architecture](ARCHITECTURE.md) — Overall system design
