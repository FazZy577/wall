# Arbitrage Opportunity Detector

P1.11 represents all prices and financial values exposed through
`EconomicBreakdown`, including financial percentages, as `Decimal`.
`confidence_score` and `opportunity_score` remain `float`. Internal values are
not automatically rounded or quantized to cents.

**Module**: `domain.interfaces.arbitrage_opportunity_detector`  
**Implementation**: `infrastructure.detectors.default_arbitrage_opportunity_detector`

## Overview

The Arbitrage Opportunity Detector evaluates whether a `CandidateListing`
represents a profitable resale opportunity by comparing its acquisition price
against an estimated market price built exclusively from `ComparableListing`
objects. The stored `ArbitrageOpportunity.listing` is the original candidate.

It provides a **BUY**, **MAYBE**, or **SKIP** recommendation based on configurable business rules.

## Core Concepts

### What is an Arbitrage Opportunity?

An arbitrage opportunity exists when you can buy an item at one price and immediately sell it at a higher price, capturing the difference as profit.

For video games on marketplaces like Wallapop, the listing price is the
acquisition price and the market estimate supplies the reference value. The
economic policy then accounts explicitly for quick-sale discount, selling
fees, fixed costs, overhead, and safety buffer before exposing net profit,
margin, ROI, acquisition discount, and break-even revenue.

### Canonical financial vocabulary

`EconomicBreakdown` is the single source of financial truth. Opportunities
delegate their read-only financial properties to it.

| Canonical name | Meaning | Denominator |
|---|---|---|
| `reference_market_value` | Gross reference market value | n/a |
| `expected_sale_revenue` | Gross expected revenue after quick-sale discount | n/a |
| `net_expected_proceeds` | Revenue after selling costs and buffer, before acquisition | n/a |
| `net_profit` | Proceeds after all costs including acquisition | n/a |
| `net_profit_margin_percentage` | Net profit margin | `expected_sale_revenue` |
| `net_roi_percentage` | Net return on investment | `total_acquisition_cost` |
| `acquisition_discount_to_reference_market_percentage` | Acquisition-price discount to reference market | `reference_market_value` |
| `break_even_sale_revenue` | Gross sale revenue required to cover costs | n/a |

Reference market is not expected revenue; expected revenue is not net
proceeds; and net proceeds do not yet subtract acquisition. The acquisition
discount uses acquisition price, while ROI uses total acquisition cost.
Break-even is revenue, not a purchase price.

### Decision Framework

The detector uses three key thresholds to determine whether a listing is worth pursuing:

| Threshold | Default Value | Description |
|-----------|---------------|-------------|
| **Minimum Profit** | EUR 10.00 | Absolute profit required to justify effort |
| **Minimum Margin** | 25% | Relative profit margin required |
| **Minimum Confidence** | 0.50 | Confidence in market price estimate |

## Recommendation Types

### BUY - Clear Opportunity

**Criteria**: ALL of the following must be true:
- Expected profit >= EUR 10.00
- Profit margin >= 25%
- Confidence score >= 0.50
- Listing price > 0

**Reason Codes**:
- `undervalued`: Listing is priced significantly below market

**Example**:
```
Listing: EUR 12.00
Market:  EUR 22.00
Profit:  EUR 10.00
Margin:  45.5%
→ BUY (undervalued)
```

### MAYBE - Borderline Case

**Criteria**: Positive profit but doesn't meet all BUY thresholds

**Reason Codes**:
- `low_expected_profit`: Profit is positive but below EUR 10.00
- `fair_price`: Margin is positive but below 25%

**Example 1** (Low Profit):
```
Listing: EUR 12.00
Market:  EUR 18.00
Profit:  EUR 6.00
Margin:  33.3%
→ MAYBE (low_expected_profit)
```

**Example 2** (Low Margin):
```
Listing: EUR 18.00
Market:  EUR 20.00
Profit:  EUR 2.00
Margin:  10%
→ MAYBE (fair_price)
```

### SKIP - Not Recommended

**Criteria**: One or more of:
- Negative or zero profit
- Low confidence in market estimate
- Invalid listing data

**Reason Codes**:
- `overpriced`: Listing price >= Market price
- `low_confidence`: Market estimate confidence < 0.50
- `invalid_listing_price`: Listing price <= 0

**Example 1** (Overpriced):
```
Listing: EUR 25.00
Market:  EUR 20.00
Profit:  EUR -5.00
→ SKIP (overpriced)
```

**Example 2** (Low Confidence):
```
Listing: EUR 10.00
Market:  EUR 25.00
Profit:  EUR 15.00
Confidence: 0.40
→ SKIP (low_confidence)
```

## Usage

### Basic Usage

```python
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)

# Create detector with default thresholds
detector = DefaultArbitrageOpportunityDetector(economic_policy)

# Evaluate a listing
opportunity = detector.detect(listing, market_estimate)

# Check recommendation
if opportunity.recommendation == Recommendation.BUY:
    print(f"BUY: Expected profit EUR {opportunity.net_profit:.2f}")
elif opportunity.recommendation == Recommendation.MAYBE:
    print(f"MAYBE: {opportunity.reason}")
else:
    print(f"SKIP: {opportunity.reason}")
```

### Custom Thresholds

```python
# More conservative thresholds
detector = DefaultArbitrageOpportunityDetector(
    min_net_profit_eur=15.0,      # Require at least EUR 15 profit
    min_net_profit_margin_percent=35.0,  # Require at least 35% margin
    min_confidence_score=0.70, # Require higher confidence
)

opportunity = detector.detect(listing, market_estimate)
```

### Get Detailed Explanation

```python
# Human-readable explanation
print(opportunity.explain())
```

Output:
```
============================================================
ARBITRAGE OPPORTUNITY ANALYSIS
============================================================

Game: Grand Theft Auto V (ps4)
Listing ID: test123

PRICING
------------------------------------------------------------
Listing Price: EUR 12.00
Estimated Market Price: EUR 22.00
Expected Profit: EUR 10.00

PROFITABILITY METRICS
------------------------------------------------------------
Profit Margin: 45.5%
ROI: 83.3%

CONFIDENCE
------------------------------------------------------------
Confidence Score: 0.80
Confidence Level: HIGH

DECISION
------------------------------------------------------------
Recommendation: BUY
Reason: undervalued

============================================================
```

## Data Model

### ArbitrageOpportunity

**Attributes**:

| Field | Type | Description |
|-------|------|-------------|
| `listing` | `CandidateListing` | Original listing considered for purchase |
| `game` | `DetectedGame` | Game detected in the listing |
| `market_price` | `float` | Estimated market price (EUR) |
| `listing_price` | `float` | Price in the listing (EUR) |
| `economic_breakdown` | `EconomicBreakdown` | Single stored source of financial values |
| `confidence_score` | `float` | Confidence in market estimate |
| `confidence_level` | `ConfidenceLevel` | Human-readable confidence |
| `recommendation` | `Recommendation` | BUY, MAYBE, or SKIP |
| `reason` | `ReasonCode` | Why this recommendation |
| `created_at` | `datetime` | Detection timestamp |

**Methods**:
- `explain() -> str`: Generate human-readable explanation

### Recommendation Enum

```python
class Recommendation(StrEnum):
    BUY = "buy"      # Clear profitable opportunity
    MAYBE = "maybe"  # Borderline case, use judgment
    SKIP = "skip"    # Not recommended
```

### ReasonCode Enum

```python
class ReasonCode(StrEnum):
    UNDERVALUED = "undervalued"              # Good deal
    FAIR_PRICE = "fair_price"                # Low margin
    OVERPRICED = "overpriced"                # Too expensive
    LOW_CONFIDENCE = "low_confidence"        # Unreliable estimate
    INSUFFICIENT_DATA = "insufficient_data"  # Not enough data
    LOW_EXPECTED_PROFIT = "low_expected_profit"  # Profit too small
    INVALID_LISTING_PRICE = "invalid_listing_price"  # Bad data
```

## Decision Logic

### Step 1: Validation

```python
if listing_price <= 0:
    return SKIP (invalid_listing_price)
```

### Step 2: Confidence Check

```python
if confidence_score < min_confidence_score:
    return SKIP (low_confidence)
```

### Step 3: Profitability Check

```python
if net_profit <= 0:
    return SKIP (overpriced)
```

### Step 4: Threshold Evaluation

```python
if (net_profit >= min_net_profit_eur AND
    net_profit_margin_percentage >= min_net_profit_margin_percent AND
    confidence >= min_confidence_score):
    return BUY (undervalued)
```

### Step 5: Borderline Cases

```python
if net_profit > 0 AND net_profit < min_net_profit_eur:
    return MAYBE (low_expected_profit)

if net_profit > 0 AND net_profit_margin_percentage < min_net_profit_margin_percent:
    return MAYBE (fair_price)
```

### Step 6: Default

```python
return MAYBE (fair_price)
```

## Calculation Formulas

### Net Profit
```
net_profit = net_expected_proceeds - total_acquisition_cost
```

### Profit Margin Percentage
```
net_profit_margin_percentage = (net_profit / expected_sale_revenue) × 100
```

**Interpretation**:
- 50% margin = You buy at half the market price
- 25% margin = You buy at 75% of market price
- 10% margin = You buy at 90% of market price

### ROI Percentage
```
net_roi_percentage = (net_profit / total_acquisition_cost) × 100
```

**Interpretation**:
- 100% ROI = You double your money
- 50% ROI = You earn 50% on your investment
- 20% ROI = You earn 20% on your investment

## Integration with Pipeline

The Arbitrage Opportunity Detector is the **final decision-making step** in the pipeline:

```
1. Scraper           → Raw listings from Wallapop
2. Game Detector     → Identify game + platform
3. Comparable Filter → Filter relevant listings
4. Dataset Builder   → Build price dataset
5. Statistics        → Calculate metrics
6. Outlier Removal   → Remove anomalous prices
7. Market Estimator  → Estimate market price
8. Arbitrage Detector → BUY/MAYBE/SKIP decision ← YOU ARE HERE
```

### Pipeline Integration Example

```python
# After market price estimation
market_estimate = market_estimator.estimate(
    dataset=clean_dataset,
    statistics=clean_stats,
    observations_removed=outlier_result.removed_count,
)

# Evaluate each listing
for listing in original_listings:
    opportunity = arbitrage_detector.detect(listing, market_estimate)
    
    if opportunity.recommendation == Recommendation.BUY:
        # Take action: notify user, save to database, etc.
        print(opportunity.explain())
```

## Testing

The module includes comprehensive tests covering:

### Test Coverage

- **BUY scenarios**: Clear buy opportunities, high profit margins
- **SKIP scenarios**: Overpriced, low confidence, invalid prices
- **MAYBE scenarios**: Low profit, fair price, borderline cases
- **Calculations**: Profit, margin, ROI formulas
- **Custom thresholds**: Configurable business rules
- **Field propagation**: All fields correctly populated
- **explain() method**: Human-readable output
- **Real-world scenarios**: Realistic arbitrage cases

### Run Tests

```bash
# Run all arbitrage detector tests
pytest tests/unit/test_default_arbitrage_opportunity_detector.py -v

# Run with coverage
pytest tests/unit/test_default_arbitrage_opportunity_detector.py --cov

# Type checking
mypy src/infrastructure/detectors/default_arbitrage_opportunity_detector.py --strict
```

## Examples

See `examples/arbitrage_detector_example.py` for complete examples showing:

1. Excellent Deal (Clear BUY)
2. Good Deal (BUY)
3. Borderline Profit (MAYBE)
4. Low Margin (MAYBE)
5. Low Confidence (SKIP)
6. Overpriced (SKIP)
7. Invalid Price (SKIP)

```bash
python examples/arbitrage_detector_example.py
```

## Configuration Guidelines

### Conservative Strategy

For risk-averse users who want high-confidence opportunities:

```python
detector = DefaultArbitrageOpportunityDetector(
    min_net_profit_eur=15.0,       # Higher profit requirement
    min_net_profit_margin_percent=35.0,   # Higher margin requirement
    min_confidence_score=0.70, # Higher confidence requirement
)
```

**Result**: Fewer BUY recommendations, but higher success rate

### Aggressive Strategy

For users willing to take more risk:

```python
detector = DefaultArbitrageOpportunityDetector(
    min_net_profit_eur=5.0,        # Lower profit requirement
    min_net_profit_margin_percent=15.0,   # Lower margin requirement
    min_confidence_score=0.40, # Lower confidence requirement
)
```

**Result**: More BUY recommendations, but lower success rate

### Balanced Strategy (Default)

Default thresholds provide a good balance:

```python
detector = DefaultArbitrageOpportunityDetector()
# min_net_profit_eur=10.0
# min_net_profit_margin_percent=25.0
# min_confidence_score=0.50
```

## Architecture Notes

### Clean Architecture

This module follows Clean Architecture principles:

- **Domain Layer** (`domain/interfaces/arbitrage_opportunity_detector.py`):
  - Defines `IArbitrageOpportunityDetector` interface (port)
  - Contains business entities: `ArbitrageOpportunity`, `Recommendation`, `ReasonCode`
  - No dependencies on infrastructure or frameworks

- **Infrastructure Layer** (`infrastructure/detectors/default_arbitrage_opportunity_detector.py`):
  - Implements the interface (adapter)
  - Contains concrete business rules
  - Can be swapped with alternative implementations

### Dependency Direction

```
Application Layer
        ↓
Domain Layer (interfaces) ← Infrastructure Layer (implementations)
```

The domain layer defines what needs to be done. The infrastructure layer defines how to do it.

### Extensibility

To create a custom arbitrage detector:

```python
class MLArbitrageOpportunityDetector(IArbitrageOpportunityDetector):
    """ML-based arbitrage detection."""
    
    def detect(
        self,
        listing: CandidateListing,
        market_estimate: MarketPriceEstimate,
    ) -> ArbitrageOpportunity:
        # Custom ML-based logic
        pass
```

## Design Decisions

### Why Separate Profit and Margin Thresholds?

Both thresholds serve different purposes:

- **Profit threshold (EUR 10)**: Ensures absolute profit justifies effort
  - Example: 50% margin on EUR 2 item = EUR 1 profit (not worth it)
  
- **Margin threshold (25%)**: Ensures relative value is good
  - Example: EUR 5 profit on EUR 100 item = 5% margin (risky)

### Why Three-Level Recommendation?

- **BUY**: High confidence, clear action
- **MAYBE**: Requires human judgment, context-dependent
- **SKIP**: Clear rejection, save time

This prevents information loss that would occur with binary YES/NO.

### Why Deterministic Rules vs. ML?

**Current approach** (Rule-based):
- Transparent and explainable
- Predictable behavior
- Easy to adjust thresholds
- No training data required

**Future approach** (ML-based):
- Could learn from historical success rates
- Could incorporate more features (condition, seller reputation)
- Requires labeled training data
- Less transparent

The rule-based approach is appropriate for MVP. ML can be added later as an alternative implementation.

## Related Documentation

- [Market Price Estimator](MARKET_PRICE_ESTIMATOR.md) - Estimates market prices
- [Price Statistics](PRICE_STATISTICS.md) - Calculates statistical metrics
- [Outlier Removal](OUTLIER_REMOVAL.md) - Removes anomalous prices
- [Architecture](ARCHITECTURE.md) - Overall system design

## Version History

- **v1.0.0** (2026-07-09): Initial implementation
  - Configurable business rules
  - Three-level recommendation system (BUY/MAYBE/SKIP)
  - Comprehensive test coverage
  - Human-readable explanations
# P1.7: explicit resale economics

Market value is the statistical reference produced by `MarketPriceEstimate`.
Expected sale revenue is the amount after the configured per-item quick-sale
discount. Net expected profit subtracts percentage fees, per-item fixed costs,
the safety reserve, purchase price, and the one-time acquisition overhead.

```text
MarketPriceEstimate
        ↓
ResaleEconomicPolicy
        ↓
EconomicBreakdown
        ↓
ArbitrageOpportunity
        ↓
Recommendation + opportunity_score
```

`net_profit` now means net expected profit. `break_even_sale_revenue`
temporarily means required gross sale revenue; its name is deferred to P1.8.
Decision thresholds, rule order, and score weights are unchanged, but their
economic inputs are net, so recommendations may legitimately become more
conservative. Values are explicit configuration, remain `float`, and no
currency conversion is performed.

## P1.12 currency invariant

Candidate, estimate and `EconomicBreakdown` must use the same canonical currency.
The detector raises `CurrencyMismatchError` before calculation when they differ.
`ArbitrageOpportunity.currency` delegates to its breakdown; no conversion or
duplicate stored currency is introduced.
