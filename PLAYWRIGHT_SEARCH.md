# Playwright Multiple Search - Proof of Concept

## ✅ Success - Multiple searches in one browser session

The script successfully performed 3 consecutive searches reusing the same Playwright browser session.

## Results Summary

### Searches Performed

1. **rdr2 ps4**
   - Status: 200 OK
   - Items: 39 listings
   - Next page: Yes (JWT token)
   - Prices: 15€, 120€, 30€, 20€, 100€
   - Saved to: `responses/rdr2_ps4.json` (176 KB)

2. **gta 5 ps4**
   - Status: 200 OK
   - Items: 40 listings
   - Next page: Yes (JWT token)
   - Prices: 25€, 24€, 12€, 15€, 14€
   - Saved to: `responses/gta_5_ps4.json` (155 KB)

3. **cod bo6 ps4**
   - Status: 200 OK
   - Items: 40 listings
   - Next page: Yes (JWT token)
   - Prices: 40€, 18€, 19€, 25€, 10€
   - Saved to: `responses/cod_bo6_ps4.json` (158 KB)

### Total Results
- **Browser sessions**: 1 (reused for all searches)
- **Total searches**: 3
- **Total listings captured**: 119
- **Total data saved**: ~489 KB

## Key Features Implemented

### 1. Browser Session Reuse ✅
- Opens Chromium **once**
- Performs multiple searches in the same session
- Closes browser only after all searches complete

### 2. Robust JSON Parsing ✅
- **No hardcoded structure assumptions**
- Recursive search functions:
  - `find_in_dict()`: Searches for keys recursively
  - `find_items_list()`: Finds item arrays automatically
  - `find_prices()`: Extracts prices from various structures

- Looks for multiple possible key names:
  - `items`, `search_objects`, `results`, `listings`, `data`

- If items not found, **prints all top-level keys** for inspection

### 3. Automatic Data Extraction ✅
- Finds `items` list regardless of nesting
- Finds `next_page` token
- Extracts prices from `price.amount` structure
- Handles missing data gracefully

### 4. Clean Output ✅
- Organized console output per search
- Shows: Status, Items count, Search ID, Next page, First 5 prices
- Saves each response to individual JSON files
- Sanitized filenames (spaces → underscores)

### 5. Error Handling ✅
- Warns if API response not captured
- Warns if items list not found
- Prints JSON structure for debugging
- Handles missing fields gracefully

## API Endpoint Confirmed

All searches hit the same endpoint:
```
https://api.wallapop.com/api/v3/search/section
```

With parameters:
- `keywords`: search query
- `source`: "deep_link"
- `search_id`: unique per search
- `latitude`, `longitude`: geolocation
- `order_by`: "most_relevance"
- `section_type`: "organic_search_results" or "vector_search_results"

## Response Structure (Confirmed)

```json
{
  "data": {
    "section": {
      "type": "organic_search_results",
      "title": "...",
      "items": [
        {
          "id": "...",
          "title": "...",
          "price": {
            "amount": 15.0,
            "currency": "EUR"
          },
          "location": {...},
          "images": [...],
          ...
        }
      ],
      "next_page": "eyJhbGciOiJIUzI1NiJ9..."  // JWT token
    }
  }
}
```

## Next Page Format

Wallapop uses JWT tokens for pagination:
- Not a simple URL with `?start=40`
- JWT token contains encrypted pagination state
- Token includes: offset, pointers, internal IDs, location, etc.

## Script Architecture

```python
# Main flow
1. Create output directory (responses/)
2. Launch Chromium browser ONCE
3. Create page context
4. For each search query:
   - Navigate to search URL
   - Capture API response via event handler
   - Parse JSON recursively
   - Extract items, prices, next_page
   - Save to file
   - Print summary
5. Close browser

# Helper functions
- find_in_dict(): Recursive key search
- find_items_list(): Smart list detection
- find_prices(): Price extraction
- sanitize_filename(): Safe file naming
- perform_search(): Single search logic
```

## Why This Approach Works

1. **No CloudFront blocking**: Real browser = real headers/cookies
2. **Session reuse**: Faster, more efficient
3. **Robust parsing**: Works even if API structure changes slightly
4. **Easy to convert**: Clean code, ready for WallapopPlaywrightClient class
5. **Debugging friendly**: Prints structure when parsing fails

## Ready for Production

This script validates that:
- ✅ Playwright can perform multiple searches efficiently
- ✅ API responses are consistent and parseable
- ✅ Session reuse works without issues
- ✅ Data extraction is robust

**Next step**: Convert this into `WallapopPlaywrightClient` class when implementing the domain layer.

## Files Created

- `examples/playwright_search.py` - Multi-search script (~210 lines)
- `responses/rdr2_ps4.json` - Search results for RDR2
- `responses/gta_5_ps4.json` - Search results for GTA 5
- `responses/cod_bo6_ps4.json` - Search results for COD BO6
- `PLAYWRIGHT_SEARCH.md` - This documentation

## How to Run

```bash
# Run the script
uv run python examples/playwright_search.py

# Results will be saved to responses/ directory
```

## Comparison: HTTP Client vs Playwright

| Feature | HTTP Client | Playwright |
|---------|-------------|------------|
| CloudFront blocking | ❌ Yes | ✅ No |
| Setup complexity | ✅ Simple | ⚠️ Requires browser |
| Speed | ✅ Fast | ⚠️ Slower (browser overhead) |
| API access | ❌ Limited | ✅ Full access |
| Cookies/auth | ❌ Manual | ✅ Automatic |
| Data completeness | ⚠️ Limited | ✅ Complete |
| **Recommended** | For simple APIs | **For Wallapop** ✅ |

---

**Conclusion**: Playwright is the recommended approach for Wallapop scraping due to CloudFront protection and automatic handling of browser state.
