# Wallapop Arbitrage - Project Setup Complete ✅

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
recommendation. Unimplemented application strategies keep their existing
score fallback pending P1.10; no lot ranking was introduced.
