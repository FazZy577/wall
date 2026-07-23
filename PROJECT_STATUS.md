# Wallapop Arbitrage - Project Setup Complete ✅

## P1.11 exact monetary representation

The complete monetary pipeline uses `Decimal`, from Infrastructure parsing
through listings, datasets, statistics, outliers, estimates and economic
breakdowns. Domain rejects monetary floats. Scores and confidence remain float.
No Money object, currency conversion, JSON encoder, cent quantization or
commercial rounding policy was introduced.

## Project Overview

Platform for detecting arbitrage opportunities in second-hand marketplaces, starting with Wallapop and designed for multi-marketplace expansion.

## P1.3 Canonical domain model definitions

`CandidateListing`, `ComparableListing`, `ListingText`, `DetectedGame`,
`GameValuation`, and `Platform` each have one canonical class definition.
The price collector port retains only a compatibility re-export of the
canonical `ComparableListing`; raw marketplace dictionaries and the filter's
minimal `Listing` payload remain intentionally distinct.

## P1.4 Application scanner use cases

Los contratos, resultados de ejecución y casos de uso de los scanners viven
en `application/interfaces` y `application/use_cases`. Domain conserva las
entidades y puertos de negocio; Infrastructure conserva los adaptadores y las
implementaciones concretas. Application no importa Infrastructure.

## P1.5 Async scanner boundary

Los casos de uso de escaneo propagan ahora la interfaz async de
`PriceCollector`: sus métodos públicos son awaitables, el procesamiento sigue
siendo secuencial y el event loop se controla únicamente desde entry points.

## P0 Wallapop Real Integration

- **HTTP client**: retained as legacy/experimental. It targets the obsolete
  `/api/v3/general/search` endpoint, which currently returns HTTP 403.
- **Production search implementation**: `WallapopPlaywrightClient` captures only
  `/api/v3/search/section`, reuses one Chromium session, supports bounded
  pagination, and is injected through the common marketplace search port.
- **Catalog**: `game_catalog.json` is packaged inside `src` and no longer depends
  on the process working directory.
- **Integration test**: opt-in live search with at most five returned listings.
- **E2E test**: opt-in real pipeline from Playwright through market price
  estimation, without persistence, lots, or `OpportunityScanner`.
- **Live test activation**: requires `RUN_LIVE_WALLAPOP_TESTS=1`; normal pytest
  runs skip live tests.
- **Live validation (2026-07-18)**: integration and minimal E2E passed with
  visible Chromium. The E2E captured 9 raw listings and produced 3 valid
  comparables for GTA V.
- **Next step**: execute and monitor the opt-in live suite periodically, then
  address any frontend/API drift as a separate task. `SearchOrchestrator`
  remains outside this P0 phase.

## ✅ What's Been Completed

### 1. Project Structure
- Clean Architecture with 3 layers: Domain → Application → Infrastructure
- Complete folder structure following best practices
- Proper separation of concerns

### 2. Development Environment
- Python 3.13 with uv package manager
- All dependencies installed in virtual environment (.venv)
- Ready for development

### 3. Code Quality Tools
- **Ruff**: Linting and formatting (configured and passing ✅)
- **MyPy**: Type checking with strict mode (configured and passing ✅)
- **Pytest**: Testing framework with coverage (2 tests passing ✅)

### 4. Project Configuration
- `pyproject.toml`: Complete project configuration
- `.gitignore`: Proper exclusions for Python projects
- `Makefile`: Common development commands
- Type hints and strict type checking enabled

### 5. Documentation
- `README.md`: Project overview and setup instructions
- `ARCHITECTURE.md`: Complete architectural documentation
- `DEVELOPMENT.md`: Development quick start guide

### 6. Initial Code Structure

```
src/
├── domain/
│   ├── entities/           # Business entities (empty, ready for implementation)
│   ├── value_objects/      # Immutable values (empty, ready for implementation)
│   └── interfaces/         # Ports/interfaces (empty, ready for implementation)
├── application/
│   └── use_cases/          # Use cases (empty, ready for implementation)
├── infrastructure/
│   ├── marketplaces/
│   │   └── wallapop/
│   │       ├── client.py   # WallapopClient placeholder
│   │       └── adapter.py  # WallapopAdapter placeholder
│   └── repositories/       # Database repos (empty, ready for implementation)
└── shared/                 # Shared utilities (empty, ready for implementation)

tests/
├── unit/
│   └── test_structure.py   # Basic structure tests (passing ✅)
├── integration/            # (empty, ready for implementation)
└── e2e/                    # (empty, ready for implementation)
```

## 🚀 Quick Start Commands

```bash
# Run all tests
uv run pytest

# Run linter
uv run ruff check src tests

# Format code
uv run ruff format src tests

# Type check
uv run mypy src

# Run all checks
uv run ruff check src tests && uv run mypy src && uv run pytest
```

## ✅ Current Status

- ✅ Project structure created
- ✅ Dependencies installed
- ✅ Development tools configured
- ✅ All quality checks passing
- ✅ Tests passing (2/2)
- ✅ Documentation complete

## 📋 Next Steps (Not Implemented Yet)

### Phase 3: Domain Layer Implementation
1. Implement core entities:
   - `Listing` (normalized listing from any marketplace)
   - `Game` (videogame catalog entry)
   - `DetectedGame` (game detected in a listing)
   - `GamePrice` (market price snapshot)
   - `Opportunity` (arbitrage opportunity)

2. Implement value objects:
   - `Money` (amount + currency)
   - `Location` (city, region, country)
   - `PriceRange` (min, max, median, percentiles)

3. Define interfaces (ports):
   - `IMarketplaceAdapter`
   - `IGameDetector`
   - `IPricingEngine`
   - `IRepository<T>`

### Phase 4: Wallapop Integration
1. Implement `WallapopClient` (HTTP client)
2. Implement `WallapopAdapter` (IMarketplaceAdapter)
3. Create integration tests

### Phase 5: First Use Case
1. Implement `ScanMarketplaceUseCase`
2. Basic persistence (JSON or SQLite)
3. End-to-end verification

## 🎯 Architecture Principles

- **Domain-Driven Design**: Rich domain model with business logic
- **Dependency Inversion**: Infrastructure depends on domain, never the opposite
- **Clean Architecture**: Clear separation of layers
- **Testability**: All components independently testable
- **Extensibility**: Easy to add new marketplaces without changing core logic

## 📝 Important Notes

- The domain layer has **zero external dependencies**
- All marketplaces return the same normalized `Listing` format
- AI is optional, not required for core functionality
- Focus on data collection and historical analysis
- Tests are designed to be fast and reliable

## 🔧 Development Workflow

1. **Before coding**: Ensure all checks pass
   ```bash
   uv run ruff check src tests && uv run mypy src && uv run pytest
   ```

2. **While coding**: Run tests frequently
   ```bash
   uv run pytest tests/unit -v
   ```

3. **Before commit**: Format and verify
   ```bash
   uv run ruff format src tests
   uv run ruff check src tests
   uv run mypy src
   uv run pytest
   ```

## 📚 Documentation Files

- `README.md` - Project overview
- `ARCHITECTURE.md` - Detailed architecture documentation
- `DEVELOPMENT.md` - Development quick start
- `PROJECT_STATUS.md` - This file

---

**Project Status**: ✅ **Ready for Domain Implementation**

All infrastructure is in place. The project is ready to start implementing the domain layer.
# P1.6 unified listing analysis

Candidate game state has been removed. Detection now occurs once at the
application boundary for both scanner flows, multi-game candidates are routed
explicitly to the lot scanner, and own-listing comparables are excluded.
# P1.7 explicit economics

Individual and lot opportunities now expose an auditable economic breakdown.
The operational 3 EUR quick-sale discount is example configuration, not a
hidden default. Fees and costs must be configured for the real sales channel;
currency conversion and migration from `float` to `Decimal` remain pending.

## P1.8 canonical financial nomenclature

`EconomicBreakdown` is now the sole stored source of financial amounts for
individual and lot opportunities. Both expose the same read-only API:
`reference_market_value`, `expected_sale_revenue`, `net_expected_proceeds`,
`net_profit`, `net_profit_margin_percentage`, `net_roi_percentage`,
`acquisition_discount_to_reference_market_percentage`, and
`break_even_sale_revenue`. Historical ambiguous financial fields and threshold
parameter names were removed rather than retained as aliases.

## P1.9 recommendation-aware ranking

Opportunity ranking now enforces `BUY > MAYBE > SKIP` before applying the
selected strategy inside each group. Scores, recommendations, counts and
tie-breakers remain unchanged. Batch scanner results retain every
recommendation. P1.10 subsequently removed the temporary duplicate strategy
path; no lot ranking was introduced.

## P1.10 canonical opportunity ranking

The batch scanner delegates exactly once to its injected
`IOpportunityRanker`. The sole strategy is `OPPORTUNITY_SCORE`, using the
stable key `BUY > MAYBE > SKIP` followed by descending score. All opportunities
are retained; fallback strategies, filtering, limits, and hidden tie-breakers
were removed. `RankingResult` only summarizes an already ordered list. Lot
ranking remains unchanged.

## P1.12 single-currency pipeline

Monetary stages require one canonical `str` currency code. Wallapop codes are
normalized without fallback, foreign-currency comparables are filtered before
datasets, and strict checks reject any remaining mix. Decimal formulas, ranking,
scores and partial-lot rules are unchanged. No Currency enum, Money, FX conversion,
exchange rate, rounding, `quantize`, or JSON serialization was introduced.

P1.14 makes dataset sample size reflect unique marketplace publications.
`DefaultPriceDatasetBuilder` now retains the first valid occurrence of each
`(platform, listing_id)` after strict validation. Candidate exclusion, currency
filtering, raw comparable caching, statistics and business rules are unchanged.

P1.15 closes the remaining identity invariant: `CandidateListing`,
`ComparableListing`, and `PriceObservation` require the same non-empty,
already-trimmed string `listing_id`. Wallapop adapters normalize only the real
payload `id`; missing or invalid IDs are discarded without synthetic fallback.

P1.16 closes comparable game identity at the collector boundary. A Wallapop
result is returned only when both its detected canonical name and platform
equal the requested game. Platforms are never treated as compatible, wildcarded
or relabelled. Cache identity, candidate exclusion, currency filtering and
builder deduplication remain unchanged.

P1.17 isolates ordinary `GameDetector` exceptions per candidate in
`scan_multiple()`. The failed candidate receives a `GAME_DETECTION` failure,
does not touch the comparable cache or later pipeline, and does not prevent
subsequent candidates from being valued and ranked. Empty detection remains a
separate result; `scan_listing()` and the lot scanner keep their prior behavior.

P1.18 distinguishes an omitted individual-detector threshold (`None`) from an
explicit numeric zero. Defaults remain 10 EUR net profit, 25 percent net profit
margin and 0.50 confidence. Rule order, comparison operators, reason codes,
score weights, economics, ranking and lot analysis are unchanged.

P1.19B makes the individual detector's absolute net-profit threshold explicit
per currency through `min_net_profit_by_currency`. `None` retains only the
historical EUR `Decimal("10.0")` default; explicit mappings are not merged with
it, empty mappings configure nothing, and missing currencies raise a diagnostic
configuration error. There is no EUR fallback or FX. Margin, confidence, score,
ranking, economics, and the lot analyzer remain unchanged.

P1.20 applies the same explicit monetary-unit safety to the separate lot
analyzer configuration. `min_net_profit_by_currency=None` retains only the
historical EUR `Decimal("10.0")` default; explicit mappings replace it, empty
mappings configure no currency, and missing currencies fail diagnostically.
There is no EUR fallback or FX. Coverage, recommendation order, reasons,
economics, `LotOpportunity`, and the individual detector remain unchanged.

P1.21B resolves the absolute resale-cost units. `ResaleAbsoluteCosts` groups
the two per-item amounts and one-time acquisition overhead;
`ResaleEconomicPolicy.absolute_costs_by_currency` selects the bundle by
pipeline currency. Ratios remain global. `neutral()` configures only EUR by
default, mappings may be empty, and missing currencies fail without EUR/zero
fallback or FX. Formulas, thresholds, scores, ranking and coverage are intact.

P1.22 makes `LotOpportunity.game_valuations` an ordered tuple snapshot. The
factory and direct constructor no longer retain a caller-owned mutable list;
later mutation of `LotScanResult.game_valuations` cannot change the opportunity
or its derived values. Order and duplicates remain intact, no deep copy is
performed, and lot economics, coverage, thresholds and recommendations do not
change.

P1.23 adds a separate structured aggregate failure to `LotScanResult`.
Analyzer exceptions retain completed valuations and game-level failures while
setting `opportunity=None` and `analysis_failure=FailureInfo(...,
stage=LOT_ANALYSIS)`. Successful BUY, MAYBE and SKIP results leave the field at
`None`; logging and `BaseException` propagation remain unchanged.

P1.24B migrates `WallapopPriceCollector` from whole-search best-effort to
propagating the original technical exception. Real empty searches still return
`[]`; per-item exceptions still warn and continue. Existing scanners and the
execution-scoped cache now distinguish empty market data from collection
failure without a new result model, exception type, retry or fallback.

P1.25B defines the Playwright gateway's defensive nested-payload contract. The
canonical empty page is a present `data.section.items=[]`; missing or incorrectly
typed `data`, `section`, `items`, `meta`, or `next_page` fields raise the existing
`WallapopSearchResponseError`. Malformed later pages fail the whole search, so
partial comparables are not returned or cached. Individual non-object items
remain isolated. This contract is based on the observed repository shape and
was implemented without live calls, retry, fallback, or scanner changes.

## P1.13 zero-IQR outlier safety

Tukey now explicitly abstains when IQR is exactly zero: no observations are
removed and effective bounds are the observed minimum and maximum. Positive-IQR
behavior is unchanged. No MAD, z-score, clipping, epsilon or fallback strategy
was added.
