# Wallapop Arbitrage Platform

Platform for detecting arbitrage opportunities in second-hand marketplaces.

## Features (Planned)

- Multi-marketplace support (Wallapop, Vinted, Milanuncios, etc.)
- Automatic game detection in listings
- Market price estimation
- Opportunity ranking
- Historical price tracking

## Architecture

Built using Clean Architecture principles:

- **Domain Layer**: Core business logic, entities, and interfaces
- **Application Layer**: Use cases and orchestration
- **Infrastructure Layer**: External adapters (APIs, databases, etc.)

## Setup

### Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager

### Installation

```bash
# Install dependencies
uv sync

# Install dev dependencies
uv sync --extra dev
```

## Development

### Running tests

```bash
uv run pytest
```

### Code quality

```bash
# Format code
uv run ruff format

# Lint code
uv run ruff check

# Type checking
uv run mypy src
```

## Project Structure

```
src/
├── domain/          # Core business logic
├── application/     # Use cases
├── infrastructure/  # External adapters
└── shared/          # Shared utilities

tests/
├── unit/            # Unit tests
├── integration/     # Integration tests
└── e2e/             # End-to-end tests
```

## License

MIT
