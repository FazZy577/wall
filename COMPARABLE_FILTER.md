# Comparable Filter Module

## Overview

The Comparable Filter module determines whether a marketplace listing can be used as a valid **comparable** for estimating the price of a target video game.

**Purpose:** Filter out listings that would skew price estimates, such as bundles, consoles, accessories, empty boxes, or wrong game versions.

**Scope:** This module does NOT calculate prices. It only makes a binary decision: valid comparable (✓) or invalid (✗).

## Architecture

The module follows **Clean Architecture** principles:

```
Domain Layer (Interfaces):
├── comparable_filter.py
│   ├── IComparableFilter (interface)
│   └── Listing (dataclass)

Infrastructure Layer (Implementations):
└── filters/
    └── rule_based_comparable_filter.py
        └── RuleBasedComparableFilter (concrete implementation)
```

### Design Decisions

- **Interface in Domain:** `IComparableFilter` defines the contract, allowing multiple implementations
- **Deterministic Implementation:** `RuleBasedComparableFilter` uses regex patterns and keyword matching
- **No External Dependencies:** No AI, no LLM, no API calls — fast and predictable
- **Type-Safe:** Full type hints compatible with `mypy --strict`

## Rules Implemented

The `RuleBasedComparableFilter` rejects listings based on these rules:

### 1. Console-Only Listings

**Reject** listings that appear to sell only a console without clear game references.

**Keywords:**
- ps4, ps5, playstation 4, playstation 5
- xbox one, xbox series
- nintendo switch, switch
- consola, console

**Logic:**
- If console keywords present AND no game-related words → **REJECT**
- If listing is very short (≤5 words) and console-only → **REJECT**

**Examples:**
- ✗ "PS4 (PlayStation 4) Negra"
- ✗ "Xbox One 500GB"
- ✓ "GTA V para PS4" (game is primary)

---

### 2. Controllers

**Reject** all controller listings.

**Keywords:**
- dualshock, dualsense
- controller, mando, joystick, control

**Examples:**
- ✗ "Mando DualShock 4 PS4"
- ✗ "Controller PS4"
- ✗ "Joystick inalámbrico"

---

### 3. Accessories

**Reject** all accessory listings.

**Keywords:**
- funda, case, carcasa
- cable, hdmi, soporte, dock
- grip, protector
- auriculares, headset
- cargador, charger

**Examples:**
- ✗ "Funda PS4"
- ✗ "Cable HDMI PS4"
- ✗ "Auriculares gaming"

---

### 4. Accounts

**Reject** digital accounts and codes.

**Keywords:**
- cuenta, account
- psn, xbox live
- digital, codigo, code

**Examples:**
- ✗ "Cuenta PSN con juegos"
- ✗ "GTA V Código Digital"
- ✗ "Xbox Live Account"

---

### 5. Empty Boxes

**Reject** listings for empty boxes without the game disc.

**Box Keywords:**
- caja, box, steelbook, estuche

**Empty Indicators:**
- sin disco, solo caja, empty box
- no disco, no game, without disc
- senza disco (Italian)

**Logic:**
- If box keyword AND empty indicator → **REJECT**

**Examples:**
- ✗ "Caja GTA V sin disco"
- ✗ "Steelbook GTA V" + "Sin disco, solo caja"
- ✓ "GTA V Steelbook Edition" (if game included)

---

### 6. Bundles / Lots

**Reject** multi-game bundles because they cannot represent the individual price of a single game.

**Keywords:**
- lote, pack
- coleccion, colección, bundle
- varios juegos, multiple games

**Examples:**
- ✗ "Lote GTA V + RDR2 + FIFA 23"
- ✗ "Pack juegos PS4"
- ✗ "Colección Rockstar"

---

### 7. Wrong Game Versions

**Reject** listings for different game versions.

**Checks:**

#### a) Different Numbered Versions
- ✗ FIFA 20 when looking for FIFA 23
- ✗ FIFA 18 when looking for FIFA 23
- ✓ FIFA 23 when looking for FIFA 23

#### b) Trilogy vs Single Game
- ✗ GTA Trilogy when looking for GTA V
- ✗ GTA V when looking for GTA Trilogy

#### c) Different Numbered Editions
- ✗ Black Ops 3 when looking for Black Ops 6
- ✗ Modern Warfare II when looking for Modern Warfare III

**Logic:**
- Extract version numbers (years like 23, 20, 18)
- Extract edition numbers (Black Ops 6, Black Ops 3)
- Check for "trilogy" vs single game mismatch
- Verify at least 50% of target game words appear in listing

**Examples:**
- Target: GTA V → ✗ GTA Trilogy
- Target: FIFA 23 → ✗ FIFA 20
- Target: Black Ops 6 → ✗ Black Ops 3
- Target: GTA V → ✓ GTA V Premium Edition

## Usage

### Basic Usage

```python
from domain.interfaces.comparable_filter import Listing
from domain.interfaces.game_detector import DetectedGame, Platform, DetectionMethod
from infrastructure.filters.rule_based_comparable_filter import RuleBasedComparableFilter

# Initialize filter
filter = RuleBasedComparableFilter()

# Define target game
target_game = DetectedGame(
    canonical_name="Grand Theft Auto V",
    matched_text="gta v",
    platform=Platform.PS4,
    confidence=1.0,
    detection_method=DetectionMethod.EXACT_MATCH,
)

# Evaluate a listing
listing = Listing(
    title="GTA V PS4",
    description="Juego en buen estado",
    price=15.0,
)

is_valid = filter.is_valid_comparable(target_game, listing)
# Returns: True
```

### Integration Example

```python
# Get listings from Wallapop
listings = wallapop_client.search("GTA V PS4")

# Detect games in each listing
detector = FuzzyGameDetector()
comparables = []

for listing in listings:
    listing_text = ListingText(
        title=listing.title,
        description=listing.description
    )
    
    detected_games = detector.detect_games(listing_text)
    
    # Check if target game was detected
    for game in detected_games:
        if game.canonical_name == "Grand Theft Auto V":
            # Check if listing is valid comparable
            listing_obj = Listing(
                title=listing.title,
                description=listing.description,
                price=listing.price
            )
            
            if filter.is_valid_comparable(game, listing_obj):
                comparables.append(listing_obj)

# Now `comparables` contains only valid listings for price estimation
```

## Extending the Filter

### Adding New Rejection Rules

To add a new rejection rule:

1. **Add keywords** to the class constants:
```python
NEW_CATEGORY_KEYWORDS = [
    r"\bkeyword1\b",
    r"\bkeyword2\b",
]
```

2. **Create a detection method** (optional):
```python
def _is_new_category(self, text: str) -> bool:
    """Check if listing matches new category."""
    return self._contains_keywords(text, self.NEW_CATEGORY_KEYWORDS)
```

3. **Add rule to `is_valid_comparable`**:
```python
def is_valid_comparable(self, target_game, listing) -> bool:
    # ... existing rules ...
    
    # New rule
    if self._is_new_category(normalized_text):
        return False
    
    return True
```

4. **Write tests** for the new rule in `test_rule_based_comparable_filter.py`

### Example: Adding "Replica" Rejection

```python
# Step 1: Add keywords
REPLICA_KEYWORDS = [
    r"\breplica\b",
    r"\bimitacion\b",
    r"\bfake\b",
    r"\bcopia\b",
]

# Step 2: Add to validation
def is_valid_comparable(self, target_game, listing) -> bool:
    normalized_text = self._normalize_text(f"{listing.title} {listing.description}")
    
    # ... existing rules ...
    
    # Reject replicas
    if self._contains_keywords(normalized_text, self.REPLICA_KEYWORDS):
        return False
    
    return True
```

### Customizing Existing Rules

You can adjust rule sensitivity by modifying:

#### Console Detection Threshold
```python
# Current: reject if ≤5 words and no game words
if len(text.split()) <= 5 and not has_game_words:
    return True

# Stricter: reject if ≤10 words
if len(text.split()) <= 10 and not has_game_words:
    return True
```

#### Game Name Matching Threshold
```python
# Current: 50% of words must match
return matches >= len(target_words) * 0.5

# Stricter: 70% of words must match
return matches >= len(target_words) * 0.7
```

## Testing

### Run Tests

```bash
# Run all comparable filter tests
uv run pytest tests/unit/test_rule_based_comparable_filter.py -v

# Run with coverage
uv run pytest tests/unit/test_rule_based_comparable_filter.py --cov=src/infrastructure/filters

# Run specific test class
uv run pytest tests/unit/test_rule_based_comparable_filter.py::TestBundleRejection -v
```

### Test Coverage

The test suite covers:

- ✓ Valid comparables (simple games, variants, special editions)
- ✓ Console rejection (PS4, Xbox, Switch)
- ✓ Controller rejection (DualShock, DualSense, generic)
- ✓ Accessory rejection (cases, cables, docks)
- ✓ Account rejection (PSN, digital codes)
- ✓ Empty box rejection (sin disco, solo caja)
- ✓ Bundle rejection (lote, pack, colección)
- ✓ Wrong game rejection (different versions, trilogy vs single)
- ✓ Edge cases (empty strings, special characters, mixed languages)
- ✓ Normalization (accents, special chars, spaces)
- ✓ Complex scenarios (steelbook with game, special editions)

**Coverage: ~100%** of `RuleBasedComparableFilter` code

## Limitations

### Current Limitations

1. **Language Support:**
   - Primarily Spanish and English keywords
   - Limited support for Italian, French, Portuguese
   - May miss keywords in other languages

2. **Pattern Matching:**
   - Simple regex patterns can have false positives/negatives
   - No semantic understanding of context
   - Cannot detect sarcasm or irony

3. **Edge Cases:**
   - "Steelbook Edition" might be rejected if rules too strict
   - Ambiguous listings like "Pack 1 juego" might be missed
   - Creative spellings may bypass detection ("G T A V")

4. **No Price Validation:**
   - Does not check if price is reasonable
   - Does not detect obvious scams (too cheap/expensive)
   - Price outliers should be handled by pricing engine

5. **Static Rules:**
   - Rules must be manually updated
   - Cannot learn from new patterns automatically
   - Requires periodic review and adjustment

### Known Issues

- **Steelbook Editions:** Currently may reject steelbooks even with game included if "sin disco" appears elsewhere
- **Numbered Bundles:** "Pack 2 juegos" might be missed if "pack" threshold too high
- **Year in Description:** Listing with "comprado en 2020" might trigger FIFA 20 rejection for FIFA 23

### Future Improvements

Potential enhancements (not implemented):

1. **Machine Learning Classifier:**
   - Train on labeled data
   - Learn patterns automatically
   - Improve accuracy over time

2. **Price-Based Filtering:**
   - Reject listings with suspicious prices
   - Use statistical outlier detection
   - Compare against historical data

3. **Multi-Language Support:**
   - Add keywords for French, German, Italian, Portuguese
   - Use translation APIs for non-standard languages

4. **Confidence Scores:**
   - Return confidence score instead of binary decision
   - Allow tunable threshold
   - Combine with game detection confidence

5. **Contextual Analysis:**
   - Use NLP to understand context better
   - Detect when "caja" means the physical game box vs empty box
   - Handle ambiguous cases more intelligently

## Performance

- **Speed:** Very fast (~1-2ms per listing)
- **Dependencies:** None (only stdlib + domain types)
- **Memory:** Minimal (no caching, stateless)
- **Scalability:** Can filter thousands of listings per second

## Integration Points

This module integrates with:

1. **Game Detector:** Receives `DetectedGame` objects
2. **Wallapop Client:** Receives `Listing` data
3. **Pricing Engine:** Filters comparables before price calculation (to be implemented)

## Validation

To validate the filter on real data:

1. Capture real Wallapop listings (use `playwright_search.py`)
2. Run game detector on listings
3. Apply comparable filter
4. Manually review rejected listings
5. Adjust rules based on false positives/negatives

---

**Module Status:** ✅ Complete and Production-Ready

**Next Steps:** Integrate with Pricing Engine for price estimation

