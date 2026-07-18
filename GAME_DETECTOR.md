# Game Detector Module

## ✅ Implementation Complete

The Game Detector module has been successfully implemented following Clean Architecture principles.

## Overview

The Game Detector module identifies video games in listing text using fuzzy string matching against a curated catalog of games.

**Key Features:**
- ✅ Deterministic detection (no AI/ML)
- ✅ Platform detection (PS4, PS5, Xbox, Switch)
- ✅ Fuzzy matching with confidence scores
- ✅ Text normalization (lowercase, accents, special chars)
- ✅ Duplicate removal
- ✅ Extensible design (ready for AI detectors)
- ✅ 26 unit tests (100% passing)
- ✅ 99% code coverage

## Architecture

### Interface (Domain Layer)

**File:** `src/domain/interfaces/game_detector.py`

Defines the contract for all game detector implementations:

```python
class IGameDetector(ABC):
    @abstractmethod
    def detect_games(self, listing_text: ListingText) -> list[DetectedGame]:
        pass
```

**Key Types:**
- `Platform`: Enum for gaming platforms (PS4, PS5, Xbox One, Xbox Series, Switch)
- `DetectionMethod`: Enum for detection methods (EXACT_MATCH, ALIAS_MATCH, FUZZY_MATCH)
- `DetectedGame`: Dataclass with canonical_name, matched_text, platform, confidence, method
- `ListingText`: Dataclass with title and description

### Implementation (Infrastructure Layer)

**File:** `src/infrastructure/detectors/fuzzy_game_detector.py`

First concrete implementation using RapidFuzz for fuzzy string matching.

**Algorithm:**
1. Normalize text (lowercase, remove accents, clean special chars)
2. Detect platform from text (PS4, PS5, etc.)
3. For each game in catalog:
   - Check if platform matches
   - Try exact substring match
   - Try fuzzy match using token_set_ratio
   - Score against all aliases
4. Filter by confidence threshold (≥80%)
5. Remove duplicates
6. Sort by confidence (highest first)

**Confidence Levels:**
- `1.00` (100%) - Exact match
- `≥0.95` (95%) - Alias match
- `≥0.90` (90%) - High fuzzy match
- `≥0.80` (80%) - Medium fuzzy match
- `<0.80` - Rejected

### Game Catalog

**File:** `data/game_catalog.json`

Contains 50 popular PS4 games with aliases:

```json
{
  "canonical_name": "Grand Theft Auto V",
  "platform": "PS4",
  "aliases": [
    "gta 5",
    "gta v",
    "gtav",
    "gta5",
    "grand theft auto v",
    "grand theft auto 5"
  ]
}
```

**Easily extensible:** Just add new games to the JSON file.

## Usage

### Basic Usage

```python
from domain.interfaces.game_detector import ListingText
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector

# Initialize detector
detector = FuzzyGameDetector()

# Create listing text
listing = ListingText(
    title="Lote PS4 GTA V RDR2 FIFA 24",
    description="Todos completos"
)

# Detect games
games = detector.detect_games(listing)

for game in games:
    print(f"{game.canonical_name} ({game.confidence:.0%})")
```

**Output:**
```
Grand Theft Auto V (100%)
Red Dead Redemption 2 (100%)
EA Sports FC 24 (100%)
```

### Custom Catalog Path

```python
detector = FuzzyGameDetector(catalog_path="path/to/catalog.json")
```

### Detection Results

Each `DetectedGame` contains:
- `canonical_name`: Official game name
- `matched_text`: Text that triggered the match
- `platform`: Detected platform (Platform enum)
- `confidence`: Score between 0.0 and 1.0
- `detection_method`: How it was detected (DetectionMethod enum)

## Testing

### Run Tests

```bash
# Run all game detector tests
uv run pytest tests/unit/test_fuzzy_game_detector.py -v

# Run with coverage
uv run pytest tests/unit/test_fuzzy_game_detector.py --cov=src
```

### Test Coverage

**26 tests covering:**
- ✅ Text normalization
- ✅ Platform detection (all platforms)
- ✅ Exact matches (GTA V, RDR2, FIFA 24, etc.)
- ✅ Variants (GTA 5, GTA5, gta v)
- ✅ Full names (Grand Theft Auto)
- ✅ Abbreviations (RDR2, FC 24)
- ✅ Multiple games in one listing
- ✅ Description text
- ✅ No false positives
- ✅ Duplicate removal
- ✅ Confidence ordering
- ✅ Detection methods
- ✅ Platform filtering

**Coverage: 99%** (1 line uncovered - error path)

## Example Script

```bash
# Run example
uv run python examples/game_detector_example.py
```

Demonstrates detection on 5 sample listings:
1. Multi-game lot → Detects 3 games
2. Games in description → Detects 3 games  
3. COD BO6 PS5 → No PS5 games in catalog yet
4. Generic "Switch games" → No specific games
5. Controller listing → Correctly detects no games

## Design Decisions

### Why No AI?

The MVP uses deterministic matching because:
- ✅ Faster (no API calls)
- ✅ Cheaper (no inference costs)
- ✅ Predictable (same input = same output)
- ✅ Testable (unit tests validate behavior)
- ✅ Offline (no external dependencies)

AI detector can be added later as alternative implementation of `IGameDetector`.

### Why Fuzzy Matching?

Users write game names inconsistently:
- "GTA5" vs "GTA 5" vs "gta v"
- "FIFA24" vs "FIFA 24" vs "FC 24"
- "rdr2" vs "Red Dead 2"

Fuzzy matching handles these variations while maintaining high accuracy.

### Why Confidence Thresholds?

Prevents false positives:
- Better to miss a game than incorrectly detect one
- High threshold (80%) ensures quality
- Confidence scores allow filtering later

### Why Platform Detection?

Avoids cross-platform confusion:
- FIFA 24 PS4 ≠ FIFA 24 PS5
- Speeds up matching (only check relevant platform)
- Enables platform-specific pricing later

## Extensibility

### Adding New Games

Edit `data/game_catalog.json`:

```json
{
  "canonical_name": "New Game Name",
  "platform": "PS4",
  "aliases": [
    "new game",
    "ng",
    "game alias"
  ]
}
```

No code changes needed.

### Adding AI Detector

Create `src/infrastructure/detectors/ai_game_detector.py`:

```python
class AIGameDetector(IGameDetector):
    def detect_games(self, listing_text: ListingText) -> list[DetectedGame]:
        # Call LLM API (Claude, Gemini, etc.)
        # Parse response
        # Return DetectedGame objects
        pass
```

Use alongside or instead of `FuzzyGameDetector`:

```python
# Use AI detector
detector = AIGameDetector()

# Or combine both
fuzzy_results = fuzzy_detector.detect_games(listing)
ai_results = ai_detector.detect_games(listing)
combined = merge_results(fuzzy_results, ai_results)
```

### Adding Image/OCR Detector

Create `src/infrastructure/detectors/ocr_game_detector.py`:

```python
class OCRGameDetector(IGameDetector):
    def detect_games(self, listing_text: ListingText) -> list[DetectedGame]:
        # OCR images from listing
        # Extract game titles from covers
        # Return DetectedGame objects
        pass
```

Same interface, different implementation.

## Quality Checks

All passing:

```bash
# Linting
uv run ruff check src/domain/interfaces/game_detector.py src/infrastructure/detectors/
# ✅ All checks passed!

# Type checking
uv run mypy src/domain/interfaces/game_detector.py src/infrastructure/detectors/
# ✅ Success: no issues found

# Tests
uv run pytest tests/unit/test_fuzzy_game_detector.py
# ✅ 26 passed in 0.72s
```

## Files Created

```
src/
├── domain/
│   └── interfaces/
│       └── game_detector.py          # Interface definition
└── infrastructure/
    └── detectors/
        ├── __init__.py
        └── fuzzy_game_detector.py    # Fuzzy matching implementation

data/
└── game_catalog.json                 # 50 PS4 games with aliases

tests/
└── unit/
    └── test_fuzzy_game_detector.py   # 26 unit tests

examples/
└── game_detector_example.py          # Usage example
```

## Next Steps

The Game Detector is **production-ready** and integrated into the architecture:

1. ✅ Interface defined in domain layer
2. ✅ Implementation in infrastructure layer
3. ✅ Fully tested (26 tests, 99% coverage)
4. ✅ Clean Architecture compliant
5. ✅ Ready for use in application layer

**Integration points:**
- Use in `DetectGamesInListingUseCase` (to be implemented)
- Combine with Wallapop scrapers (Playwright/HTTP)
- Feed results to pricing engine
- Store in repositories

---

**Game Detector Module: ✅ Complete**
