# Development Quick Start

## First Time Setup

```bash
# Install uv if not already installed
python -m pip install uv

# Install all dependencies (including dev dependencies)
uv sync --extra dev
```

## Common Commands

### Testing

```bash
# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=src --cov-report=html

# Run only unit tests
uv run pytest tests/unit -v

# Run only integration tests
uv run pytest tests/integration -v

# Run specific test file
uv run pytest tests/unit/test_structure.py -v
```

### Code Quality

```bash
# Check code with ruff (linter)
uv run ruff check src tests

# Format code with ruff
uv run ruff format src tests

# Type check with mypy
uv run mypy src

# Run all quality checks
uv run ruff check src tests && uv run mypy src && uv run pytest
```

### Development

```bash
# Activate virtual environment (if needed for IDE)
# Windows
.venv\Scripts\activate
# Unix/MacOS
source .venv/bin/activate

# Run Python REPL with project imports available
uv run ipython
```

## Project Structure

```
src/
├── domain/              # Core business logic (no external dependencies)
│   ├── entities/        # Business entities (Listing, Game, Opportunity, etc.)
│   ├── value_objects/   # Immutable values (Money, Location, etc.)
│   └── interfaces/      # Ports/interfaces for adapters
├── application/         # Use cases and orchestration
│   └── use_cases/
├── infrastructure/      # External adapters and implementations
│   ├── marketplaces/    # Marketplace adapters (Wallapop, etc.)
│   └── repositories/    # Database repositories
└── shared/              # Shared utilities

tests/
├── unit/                # Fast, isolated tests
├── integration/         # Tests with external dependencies
└── e2e/                 # End-to-end tests
```

## Architecture Principles

- **Clean Architecture**: Domain → Application → Infrastructure
- **Dependency Rule**: Dependencies point inward (Infrastructure depends on Domain, never the other way)
- **Testability**: All layers are independently testable
- **Extensibility**: New marketplaces can be added without modifying core logic

## Next Steps

1. ✅ Project structure created
2. ✅ Development tools configured (ruff, mypy, pytest)
3. ✅ Basic tests passing
4. 🔄 Implement domain entities
5. 🔄 Implement Wallapop adapter
6. 🔄 Create first use case (ScanMarketplace)

See `ARCHITECTURE.md` for detailed architecture documentation.
