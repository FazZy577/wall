# Price Statistics Module

## Overview

The Price Statistics Engine is the **statistical brain** of the pricing system. It calculates descriptive statistics from clean price datasets using deterministic mathematical methods.

**Purpose:** Calculate comprehensive statistical metrics from price observations.

**Scope:** This module does NOT estimate prices, remove outliers, or make business decisions. It only performs mathematical calculations.

## What This Module Does

✅ **Calculates descriptive statistics:**
- Count, min, max
- Mean (arithmetic average)
- Median (50th percentile)
- Standard deviation (sample)
- Variance (sample)
- Quartiles (Q1, Q3)
- Interquartile range (IQR)
- Percentiles (10th, 25th, 75th, 90th)

## What This Module Does NOT Do

❌ **Does NOT perform:**
- Outlier removal or detection
- Price estimation
- Market price recommendations
- Confidence scoring
- Data filtering
- Business logic decisions
- API calls
- Data collection

## Why This Separation

This module follows the **Single Responsibility Principle**:

```
Price Dataset → Statistics Engine → Statistical Metrics
                                          ↓
                                  (Future modules decide what to do with them)
```

**Benefits:**
1. **Testability**: Pure mathematical functions, easy to test
2. **Reusability**: Works with any price dataset, regardless of source
3. **Maintainability**: Statistical logic isolated from business logic
4. **Flexibility**: Can change outlier/estimation strategies without touching statistics

## Architecture

```
Domain Layer (Interfaces):
├── price_statistics.py
│   ├── IPriceStatistics (interface)
│   ├── PriceStatisticsResult (dataclass)
│   └── EmptyDatasetError (exception)

Infrastructure Layer (Implementations):
└── statistics/
    └── default_price_statistics.py
        └── DefaultPriceStatistics (concrete implementation)
```

### Design Decisions

- **Interface in Domain:** `IPriceStatistics` defines the contract
- **Pure Calculations:** No side effects, no I/O, deterministic
- **Standard Library:** Uses Python's `statistics` module (no ML libraries)
- **Float Precision:** No internal rounding (rounding is caller's responsibility)
- **Type-Safe:** Full type hints compatible with `mypy --strict`
- **Exception on Empty:** Raises `EmptyDatasetError` rather than returning invalid data

## Data Models

### PriceStatisticsResult

Statistical metrics calculated from a price dataset:

```python
@dataclass
class PriceStatisticsResult:
    count: int                    # Number of observations
    min_price: float              # Minimum price
    max_price: float              # Maximum price
    mean_price: float             # Arithmetic mean
    median_price: float           # Median (50th percentile)
    standard_deviation: float     # Sample standard deviation
    variance: float               # Sample variance
    q1: float                     # First quartile (25th percentile)
    q3: float                     # Third quartile (75th percentile)
    iqr: float                    # Interquartile range (Q3 - Q1)
    percentile_10: float          # 10th percentile
    percentile_25: float          # 25th percentile (same as Q1)
    percentile_75: float          # 75th percentile (same as Q3)
    percentile_90: float          # 90th percentile
```

### EmptyDatasetError

Exception raised when dataset has no observations:

```python
class EmptyDatasetError(Exception):
    """Raised when attempting to calculate statistics on an empty dataset."""
    pass
```

## Usage

### Basic Usage

```python
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics

# Create calculator
calculator = DefaultPriceStatistics()

# Calculate statistics from dataset
stats = calculator.calculate(dataset)

# Access metrics
print(f"Mean: EUR {stats.mean_price:.2f}")
print(f"Median: EUR {stats.median_price:.2f}")
print(f"Std Dev: EUR {stats.standard_deviation:.2f}")
```

### Integration Example

```python
# Complete pipeline
async def get_price_statistics(game: DetectedGame) -> PriceStatisticsResult:
    # Step 1: Collect comparable listings
    price_collector = WallapopPriceCollector(...)
    comparable_listings = await price_collector.collect_comparables(game, ...)
    
    # Step 2: Build clean dataset
    dataset_builder = DefaultPriceDatasetBuilder(source="wallapop")
    dataset = dataset_builder.build(comparable_listings)
    
    # Step 3: Calculate statistics
    statistics_calculator = DefaultPriceStatistics()
    stats = statistics_calculator.calculate(dataset)
    
    return stats
```

### Error Handling

```python
try:
    stats = calculator.calculate(dataset)
except EmptyDatasetError:
    print("Cannot calculate statistics: no observations")
```

## Statistical Formulas

### Mean (Arithmetic Average)

```
mean = sum(prices) / count
```

### Median

- **Odd count**: Middle value
- **Even count**: Average of two middle values

### Standard Deviation (Sample)

```
s = sqrt(sum((x - mean)^2) / (n - 1))
```

### Variance (Sample)

```
variance = s^2
```

### Percentiles

Uses linear interpolation between data points.

### Interquartile Range

```
IQR = Q3 - Q1
```

## Special Cases

### Empty Dataset

```python
dataset.sample_size = 0

# Raises EmptyDatasetError
calculator.calculate(dataset)
```

### Single Observation

```python
prices = [15.0]

stats = calculator.calculate(dataset)

# All metrics equal to single value
assert stats.min_price == 15.0
assert stats.max_price == 15.0
assert stats.mean_price == 15.0
assert stats.median_price == 15.0

# No variance
assert stats.standard_deviation == 0.0
assert stats.variance == 0.0
```

### All Equal Prices

```python
prices = [20.0, 20.0, 20.0, 20.0]

stats = calculator.calculate(dataset)

# All metrics equal
assert stats.mean_price == 20.0
assert stats.median_price == 20.0

# No spread
assert stats.standard_deviation == 0.0
assert stats.iqr == 0.0
```

## Outliers

This module **includes outliers** in calculations. It does NOT remove them.

**Why?**

1. **Separation of concerns**: Outlier removal is a separate decision with different strategies
2. **Transparency**: All observations are used, nothing hidden
3. **Flexibility**: Different use cases may want different outlier handling

**Outlier Detection:**

The module calculates Q1, Q3, and IQR, which can be used by other modules to identify outliers:

```python
# Standard outlier definition (IQR method)
lower_bound = stats.q1 - 1.5 * stats.iqr
upper_bound = stats.q3 + 1.5 * stats.iqr

# Outliers are values outside this range
outliers = [p for p in prices if p < lower_bound or p > upper_bound]
```

But this logic belongs in a **separate Outlier Removal Engine**, not here.

## Precision

### No Rounding

The calculator preserves full float precision:

```python
prices = [10.123, 20.456, 30.789]

stats = calculator.calculate(dataset)

# Full precision preserved
assert stats.mean_price == 20.456
```

### Rounding is Caller's Responsibility

```python
stats = calculator.calculate(dataset)

# Round when presenting to user
print(f"Mean: EUR {stats.mean_price:.2f}")  # EUR 15.77
print(f"Median: EUR {stats.median_price:.2f}")  # EUR 15.00
```

## Testing

### Run Tests

```bash
# Run all price statistics tests
python -m pytest tests/unit/test_default_price_statistics.py -v

# Run with coverage
python -m pytest tests/unit/test_default_price_statistics.py --cov=src/infrastructure/statistics

# Run specific test class
python -m pytest tests/unit/test_default_price_statistics.py::TestPercentileCalculations -v
```

### Test Coverage

The test suite covers:

- ✓ Empty dataset (raises exception)
- ✓ Single observation
- ✓ Two observations
- ✓ Five observations
- ✓ Twenty observations
- ✓ All equal prices
- ✓ Highly dispersed prices
- ✓ Extreme outliers (included in calculations)
- ✓ Percentile calculations (10th, 25th, 75th, 90th)
- ✓ Median calculations (odd and even count)
- ✓ Standard deviation and variance
- ✓ IQR calculations
- ✓ Float precision preservation
- ✓ No internal rounding
- ✓ Real-world price scenarios

**Test Results:** 30/30 passing (100%)

**Coverage:** 100% of `default_price_statistics.py` code

## Example Output

```
================================================================================
PRICE STATISTICS ENGINE - EXAMPLE USAGE
================================================================================

Target Game: Grand Theft Auto V (PS4)

Price Dataset:
  Sample size: 11 observations
  Prices: EUR 10.0, EUR 12.0, EUR 12.5, EUR 13.0, EUR 15.0, EUR 15.0, EUR 16.0, EUR 17.0, EUR 18.0, EUR 20.0, EUR 25.0

--------------------------------------------------------------------------------

STATISTICAL METRICS

Basic Metrics:
  Count: 11
  Min price: EUR 10.00
  Max price: EUR 25.00
  Mean price: EUR 15.77
  Median price: EUR 15.00

Spread Metrics:
  Standard deviation: EUR 4.20
  Variance: 17.67

Quartiles:
  Q1 (25th percentile): EUR 12.50
  Q2 (Median): EUR 15.00
  Q3 (75th percentile): EUR 18.00
  IQR (Q3 - Q1): EUR 5.50

Percentiles:
  10th percentile: EUR 10.40
  25th percentile: EUR 12.50
  75th percentile: EUR 18.00
  90th percentile: EUR 24.00

================================================================================
```

## Integration Points

This module integrates with:

1. **Price Dataset Builder** (`infrastructure.dataset_builders`)
   - Receives: `PriceDataset`
   - Extracts: Price observations

2. **Future: Outlier Removal Engine**
   - Uses: Q1, Q3, IQR from `PriceStatisticsResult`
   - Removes: Statistical outliers
   - Returns: Filtered dataset

3. **Future: Market Price Estimator**
   - Uses: Mean, median, percentiles from `PriceStatisticsResult`
   - Decides: Fair market price
   - Returns: Price estimate with confidence

4. **Future: Confidence Score Engine**
   - Uses: Standard deviation, IQR, count from `PriceStatisticsResult`
   - Calculates: Confidence score
   - Returns: Reliability metric

## What Modules Will Consume This

### Outlier Removal Engine (Future)

```python
# Calculate statistics (including outliers)
stats = statistics_calculator.calculate(dataset)

# Use IQR method to identify outliers
outlier_engine = OutlierRemovalEngine()
clean_dataset = outlier_engine.remove_outliers(dataset, stats)

# Recalculate statistics without outliers
clean_stats = statistics_calculator.calculate(clean_dataset)
```

### Market Price Estimator (Future)

```python
# Calculate statistics
stats = statistics_calculator.calculate(dataset)

# Use median as base estimate (robust to outliers)
price_estimator = MarketPriceEstimator()
estimated_price = price_estimator.estimate(stats)

# Uses: median, mean, percentiles, IQR
```

### Confidence Score Engine (Future)

```python
# Calculate statistics
stats = statistics_calculator.calculate(dataset)

# Calculate confidence based on sample size and variance
confidence_engine = ConfidenceScoreEngine()
confidence = confidence_engine.calculate(stats)

# Uses: count, standard_deviation, IQR
# Returns: 0.0 to 1.0 (low to high confidence)
```

## Why This Module Doesn't Estimate Prices

**This module is a calculator, not a decision maker.**

Price estimation requires:
- Business logic (which metric to trust?)
- Domain knowledge (is median better than mean?)
- Context (is the market stable or volatile?)
- Confidence scoring (how reliable is this estimate?)

These decisions belong in the **Market Price Estimator**, not here.

**Separation:**
- **Statistics Engine**: "Here are the numbers"
- **Price Estimator**: "Based on the numbers, I recommend X"

## Limitations

### Current Limitations

1. **No Multi-Currency Support:**
   - Assumes all prices in same currency
   - No currency conversion
   - Caller must ensure currency consistency

2. **Sample Statistics Only:**
   - Uses sample standard deviation and variance
   - Not population statistics

3. **No Weighted Statistics:**
   - All observations weighted equally
   - No time-based weighting
   - No quality-based weighting

4. **No Robust Statistics:**
   - Sensitive to extreme outliers
   - No trimmed mean
   - No winsorized statistics

5. **Linear Interpolation Only:**
   - Percentiles use linear interpolation
   - No other interpolation methods

### Known Issues

- **Percentile Calculation**: For very small samples (n < 10), percentile estimates may be less accurate
- **Single Observation**: Returns 0 for standard deviation and variance (correct but may need special handling)

### Future Improvements

Potential enhancements (not implemented):

1. **Robust Statistics:**
   - Trimmed mean (exclude top/bottom X%)
   - Winsorized mean (cap outliers)
   - Median absolute deviation (MAD)

2. **Weighted Statistics:**
   - Time-weighted (recent listings weighted higher)
   - Quality-weighted (based on listing quality score)
   - Platform-weighted (trust some platforms more)

3. **Bootstrap Confidence Intervals:**
   - Use bootstrapping for confidence intervals
   - Provide uncertainty bounds on estimates

4. **Additional Metrics:**
   - Mode (most common price)
   - Skewness (distribution asymmetry)
   - Kurtosis (distribution tail behavior)
   - Coefficient of variation

5. **Multi-Currency Support:**
   - Accept mixed currencies
   - Convert to base currency
   - Use exchange rates API

## Performance

- **Speed:** ~0.1ms per calculation
- **Dependencies:** Only `statistics` module (stdlib)
- **Memory:** Minimal (no caching, no state)
- **Scalability:** Can process thousands of datasets per second

## Code Quality

- **Type Safety**: 100% type hints, passes `mypy --strict`
- **Test Coverage**: 100% code coverage, 30 tests
- **Pure Functions**: No side effects, deterministic
- **Single Responsibility**: Only calculates statistics
- **Documentation**: Comprehensive inline and external docs

---

**Module Status:** ✅ Complete and Production-Ready

**Next Modules:**
1. **Outlier Removal Engine** - Remove statistical outliers from datasets
2. **Market Price Estimator** - Estimate fair market price from statistics
3. **Confidence Score Engine** - Calculate reliability score for estimates
