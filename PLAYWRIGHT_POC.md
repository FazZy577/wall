# Playwright Capture - Proof of Concept

## ✅ Success

The Playwright script successfully captured the Wallapop API response.

## Results

### API Endpoint Captured
```
https://api.wallapop.com/api/v3/search/section?keywords=lote+ps4&source=deep_link&search_id=acb1119b-2365-4290-9314-1f5035d020ab&latitude=41.1185&longitude=1.254&order_by=most_relevance&section_type=organic_search_results
```

### Response Summary
- **Status**: 200 OK
- **Total items**: 40 listings
- **Next page**: No (all results in one page)
- **Response saved to**: `response.json`

### Response Structure

The API returns a different structure than expected:

```json
{
  "data": {
    "section": {
      "type": "organic_search_results",
      "title": "Encuentra lo que buscas",
      "items": [
        {
          "id": "wzyrp135de65",
          "user_id": "3zlgx03kgnjx",
          "title": "Lote Juegos PS4/PS5, vendo cualquier juego.",
          "description": "...",
          "category_id": 24200,
          "price": {
            "amount": 140.0,
            "currency": "EUR"
          },
          "images": [...],
          "location": {
            "latitude": 37.942682558558424,
            "longitude": -4.687816030944092,
            "postal_code": "14029",
            "city": "Cañuelo Bajo",
            "region": "Andalucía",
            "region2": "Córdoba",
            "country_code": "ES"
          },
          "shipping": {
            "item_is_shippable": true,
            "user_allows_shipping": true
          },
          "web_slug": "lote-juegos-ps4-ps5-vendo-cualquier-juego-1279953192",
          "created_at": 1783531375986,
          "modified_at": 1783531428141,
          "taxonomy": [...],
          ...
        }
      ],
      "next_page": null
    }
  }
}
```

### Key Differences from HTTP Client

1. **Different endpoint**: `/api/v3/search/section` instead of `/api/v3/general/search`
2. **Different structure**: Data wrapped in `data.section.items` instead of `search_objects`
3. **More metadata**: Includes `taxonomy`, `shipping`, `bump`, `favorited`, etc.
4. **Richer location data**: Includes postal_code, region, region2, country_code
5. **Image URLs**: Multiple sizes (small, medium, big)

### Example Listings Found

1. **Lote Juegos PS4/PS5, vendo cualquier juego.**
   - Price: 140.0 EUR
   - ID: wzyrp135de65

2. **Pack Bioshock PS4 (PlayStation 4)**
   - Price: 24.0 EUR
   - ID: nzxenx83om62

## Files Created

- `examples/playwright_capture.py` - Playwright capture script (~70 lines)
- `response.json` - Full API response (40 listings, ~1.5MB)

## How to Run

```bash
# Install Playwright browsers (one time)
uv run playwright install chromium

# Run capture script
uv run python examples/playwright_capture.py
```

## Conclusion

✅ **Playwright approach works perfectly**

- Captures real browser API calls
- Gets complete JSON responses
- No CloudFront blocking (browser has proper cookies/headers)
- More data than direct HTTP approach

This proves Playwright is a viable approach for the WallapopAdapter implementation.
