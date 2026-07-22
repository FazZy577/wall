# Lot Domain Model

**Entities**: `src/domain/entities/`

## Overview

The lot domain model introduces three new entities that enable analyzing bundles (lots) of multiple video games, without modifying the existing individual opportunity pipeline.

## Key Distinction

### CandidateListing vs ComparableListing

| | CandidateListing | ComparableListing |
|---|---|---|
| **Purpose** | Listing we are considering **buying** | Listing used as a **price reference** |
| **Game count** | `detected_games: list[DetectedGame]` (multiple) | `detected_game: DetectedGame` (single) |
| **Used in** | Lot valuation, purchase decisions | Market price estimation dataset |
| **Location** | `domain/entities/candidate_listing.py` | `domain/entities/comparable_listing.py` |

**Example**: For a lot "GTA V + RDR2 + Spider-Man at 40€":

- `CandidateListing` represents the lot itself (40€, 3 games)
- `ComparableListing` represents individual GTA V listings at 15€, 18€, 20€ used to estimate GTA V's market price

### ArbitrageOpportunity vs LotOpportunity

| | ArbitrageOpportunity | LotOpportunity |
|---|---|---|
| **Scope** | Single game | Bundle of games |
| **Game field** | `game: DetectedGame` (singular) | `game_valuations: list[GameValuation]` (plural) |
| **Market price** | Single game's market price | Sum of all games' market values |
| **Profit** | `market_price - listing_price` | `reference_market_value - lot_price` |
| **Confidence** | Single estimate's confidence | Aggregate (mean) of individual confidences |
| **Reason** | `ReasonCode` (individual) | `LotReasonCode` (lot-specific) |

## Why ArbitrageOpportunity Was Not Modified

`ArbitrageOpportunity` represents a single-game opportunity. It has:
- `game: DetectedGame` (singular)
- `market_price: float` (single value)
- `listing: CandidateListing` (single-game purchase candidate)

Converting `game` to a list would break the existing individual pipeline. Instead, `LotOpportunity` is a separate entity that composes multiple `GameValuation` objects.

## Entities

### CandidateListing

```python
@dataclass
class CandidateListing:
    listing_id: str
    title: str
    description: str
    price: float
    currency: str
    url: str
    detected_games: list[DetectedGame] = field(default_factory=list)
    raw_listing: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    seller_id: str | None = None

    @property
    def is_lot(self) -> bool:  # True when len(detected_games) > 1
    @property
    def game_count(self) -> int:  # len(detected_games)
```

### GameValuation

```python
@dataclass
class GameValuation:
    game: DetectedGame
    market_price_estimate: MarketPriceEstimate
    estimated_market_value: float  # = market_price_estimate.estimated_price
    confidence_score: float       # = market_price_estimate.confidence_score
    observations_used: int         # = market_price_estimate.sample_size
    observations_removed: int      # outliers removed
    created_at: datetime
```

Created via `GameValuation.from_market_estimate(game, estimate, observations_removed)`.

### LotOpportunity

```python
@dataclass
class LotOpportunity:
    listing: CandidateListing
    game_valuations: list[GameValuation]
    lot_price: float
    aggregate_confidence_score: float
    recommendation: Recommendation
    reason: LotReasonCode
    opportunity_score: float
    created_at: datetime
    economic_breakdown: EconomicBreakdown
```

All financial values are read-only properties delegated to
`economic_breakdown`; they are not duplicated dataclass fields.

Created via `LotOpportunity.from_valuations(listing, valuations, recommendation, reason, score)`.

### LotReasonCode

```python
class LotReasonCode(StrEnum):
    UNDERVALUED_LOT = "undervalued_lot"
    FAIR_VALUE_LOT = "fair_value_lot"
    OVERPRICED_LOT = "overpriced_lot"
    LOW_AGGREGATE_CONFIDENCE = "low_aggregate_confidence"
    INCOMPLETE_VALUATION = "incomplete_valuation"
    NO_GAMES_DETECTED = "no_games_detected"
    INVALID_LOT_PRICE = "invalid_lot_price"
```

## Calculations

```
reference_market_value = sum(successful game reference values)
expected_sale_revenue = sum(per-item values after quick-sale discount)
net_profit = net_expected_proceeds - total_acquisition_cost
net_profit_margin_percentage = net_profit / expected_sale_revenue * 100
net_roi_percentage = net_profit / total_acquisition_cost * 100
aggregate_confidence_score = mean(confidence_score for each valuation)
```

### Edge cases

| Case | Behavior |
|---|---|
| `expected_sale_revenue <= 0` | `net_profit_margin_percentage = 0.0` |
| `total_acquisition_cost <= 0` | `net_roi_percentage = 0.0` |
| `reference_market_value <= 0` | acquisition discount = `0.0` |
| No valuations | `aggregate_confidence_score = 0.0`, `reference_market_value = 0.0` |

### aggregate_confidence_score

Currently uses **arithmetic mean**. This is documented as a simplification and may be replaced by a weighted mean (weighted by `observations_used`) in the future.

## Dataset Contamination Rule

**The candidate listing price MUST NOT appear in the price dataset.**

The `PriceDataset` used to estimate market prices must contain ONLY `ComparableListing` objects returned by `PriceCollector`. The candidate listing's price would contaminate the market estimate.

**Before (incorrect):**
```
dataset = [candidate(40€), comp1(12€), comp2(15€), comp3(18€)]
market_estimate = median(40, 12, 15, 18) = 16.5€  ← skewed by candidate
```

**After (correct):**
```
dataset = [comp1(12€), comp2(15€), comp3(18€)]
market_estimate = median(12, 15, 18) = 15€  ← pure market signal
```

This was fixed in `DefaultOpportunityScanner` (lines 155-158, 270-274) by removing `[listing] +` from the dataset construction.

## Example: Lot Valuation

```python
# Lot: "Lote PS4 GTA V RDR2 Spider-Man" at 40 EUR
candidate = CandidateListing(
    listing_id="lot001",
    title="Lote PS4 GTA V RDR2 Spider-Man",
    price=40.0,
    currency="EUR",
    detected_games=[gta_v, rdr2, spider_man],
)

# Each game valued individually
valuations = [
    GameValuation.from_market_estimate(gta_v, estimate_gta_v),      # 15€
    GameValuation.from_market_estimate(rdr2, estimate_rdr2),        # 20€
    GameValuation.from_market_estimate(spider_man, estimate_spidey), # 18€
]

# Lot opportunity
lot = LotOpportunity.from_valuations(
    candidate, valuations,
    recommendation=BUY,
    reason=UNDERVALUED_LOT,
    opportunity_score=85.0,
)

# Results:
# reference_market_value = 15 + 20 + 18 = 53€
# net_profit = 53 - 40 = 13€
# profit_margin = 13/53*100 = 24.5%
# roi = 13/40*100 = 32.5%
```

## Future Integration

The lot domain model is designed to be used by a future `LotOpportunityScanner`:

```
CandidateListing (lot)
    │
    ▼
For each game in detected_games:
    PriceCollector → Dataset → Stats → Outlier → Estimate → GameValuation
    │
    ▼
LotOpportunity.from_valuations(candidate, valuations, ...)
    │
    ▼
OpportunityRanker.rank(lot_opportunities)
```

## Related Documentation

- [Opportunity Scanner](OPPORTUNITY_SCANNER.md) — Individual game pipeline
- [Opportunity Ranker](OPPORTUNITY_RANKER.md) — Ranking logic
- [Arbitrage Opportunity](ARBITRAGE_OPPORTUNITY.md) — Individual opportunity entity
# P1.6 detection ownership

`CandidateListing` is marketplace input only and has no `detected_games`,
`game_count`, or `is_lot` state. Whether it represents a lot is established by
the `GameDetector` result inside the appropriate application use case.
# P1.7 economic breakdown

`LotOpportunity` contains one mandatory `EconomicBreakdown`. Gross market
value remains available, while profit, margin, and ROI use net proceeds,
expected sale revenue, and total acquisition cost respectively. Net proceeds
and profit may be negative.
