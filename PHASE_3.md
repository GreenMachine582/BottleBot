# Phase 3 — Breadth: More Sources & Normalisation

> **Goal:** Expand coverage to BWS, Liquorland, First Choice Liquor, Vintage Cellars, and CellarMasters. Normalise products across retailers so the same bottle can be compared cross-site, and introduce robust CPL (cost per litre) calculations as the primary comparison metric.

**Status:** ✅ Complete

**Estimated effort:** 2–3 weekends
**Depends on:** Phase 1 (scraper architecture), Phase 2 (scoring pipeline)
**Unlocks:** Phase 4 (cross-retailer comparison in the UI)

---

## Deliverables

- [x] BWS scraper, with tenacity retries and its subscription key loaded from `.env` via `Settings` — [`src/scrapers/bws.py`](./src/scrapers/bws.py)
- [x] Shared Coles Group base scraper using curl_cffi to avoid TLS-fingerprint bot detection — [`src/scrapers/coles_group.py`](./src/scrapers/coles_group.py)
- [x] Liquorland scraper — [`src/scrapers/liquorland.py`](./src/scrapers/liquorland.py)
- [x] First Choice Liquor scraper — [`src/scrapers/firstchoice.py`](./src/scrapers/firstchoice.py)
- [x] Vintage Cellars scraper — [`src/scrapers/vintagecellars.py`](./src/scrapers/vintagecellars.py)
- [x] CellarMasters scraper (wine focus) — [`src/scrapers/cellarmasters.py`](./src/scrapers/cellarmasters.py)
- [x] Cross-retailer product deduplication / matching — [`src/db/matching.py`](./src/db/matching.py)
- [x] Category taxonomy normalisation — [`src/scrapers/taxonomy.py`](./src/scrapers/taxonomy.py)
- [x] Robust CPL calculation with volume parsing edge cases — [`src/scrapers/utils.py`](./src/scrapers/utils.py)
- [x] Cross-retailer deal comparison (same product, cheapest retailer wins) — [`src/scoring/cross_retailer.py`](./src/scoring/cross_retailer.py)
- [x] `upsert_product` updated to link new RetailerProducts to existing Products via matching — [`src/db/writer.py`](./src/db/writer.py)
- [x] `Settings` extended with `bws_subscription_key` — [`src/config/settings.py`](./src/config/settings.py)
- [x] Scheduler updated for all sources with staggered timing — [`src/scheduler.py`](./src/scheduler.py)
- [x] Tests for all new scrapers, matching, cross-retailer comparison, utils, and taxonomy — [`tests/`](./tests/)

---

## 1. Scraper architecture

Phase 1 established `BaseScraper`. All new scrapers implement the same interface.

```
src/scrapers/
├── base.py              ✅ Phase 1
├── danmurphys.py        ✅ Phase 1
├── utils.py             ✅ Phase 3 — parse_volume_ml(), calc_cpl()
├── taxonomy.py          ✅ Phase 3 — normalise_category()
├── coles_group.py       ✅ Phase 3 — shared base for Coles properties
├── bws.py               ✅ Phase 3
├── liquorland.py        ✅ Phase 3
├── firstchoice.py       ✅ Phase 3
├── vintagecellars.py    ✅ Phase 3
└── cellarmasters.py     ✅ Phase 3
```

Each scraper only needs to implement `scrape_deals()`. The persistence layer, scoring, and alerting are unchanged.

---

## 2. Retailer scrapers

### BWS

[`src/scrapers/bws.py`](./src/scrapers/bws.py) — BWS shares the Endeavour Group backend with Dan Murphy's. It exposes a stable internal JSON API (`api.bws.com.au/apis/ui/v3/Products/Category/specials`) that's more reliable than rendered HTML. The scraper:

- Passes `subscription-key` from `settings.bws_subscription_key` (`BOTTLEBOT_BWS_SUBSCRIPTION_KEY` in `.env`) — see [`src/config/settings.py`](./src/config/settings.py)
- Reads `PackageSize.Millilitres` for volume; falls back to `parse_volume_ml()` on the description when the field is absent (multi-pack products often omit it)
- Uses `normalise_category()` from [`taxonomy.py`](./src/scrapers/taxonomy.py) to map `SubType` (e.g. `"scotch whisky"`) to a canonical category (e.g. `"whisky"`)
- Wraps the HTTP call in `@retry(stop_after_attempt(3), wait_exponential(...))` via tenacity, inside a non-generator `_fetch_deals()` — keeping the retry decorator off the generator itself (see Known gotchas)

> **API key:** Check the Network tab when browsing bws.com.au — look for requests to `api.bws.com.au`. Extract the `subscription-key` header value and add it to `.env` as `BOTTLEBOT_BWS_SUBSCRIPTION_KEY`. This key changes infrequently.

---

### Liquorland, First Choice Liquor, Vintage Cellars (Coles Group)

All three are Coles Group properties running near-identical storefronts. Rather than duplicating scraper code three times, a shared base class [`src/scrapers/coles_group.py`](./src/scrapers/coles_group.py) holds all the logic; each retailer is a 3-line subclass that sets `retailer` and `DEALS_URL`:

- [`src/scrapers/liquorland.py`](./src/scrapers/liquorland.py) — `https://www.liquorland.com.au/specials`
- [`src/scrapers/firstchoice.py`](./src/scrapers/firstchoice.py) — `https://www.firstchoiceliquor.com.au/specials`
- [`src/scrapers/vintagecellars.py`](./src/scrapers/vintagecellars.py) — `https://www.vintagecellars.com.au/specials`

`ColesGroupScraper` parses JSON-LD `<script type="application/ld+json">` tags embedded by the server — more stable than CSS selectors. Volume is parsed from the product name via `parse_volume_ml()`. Category is read from the JSON-LD `category` field if present and normalised via `normalise_category()`.

Coles Group fingerprints the TLS/JA3 handshake of generic HTTP clients and 403s plain `httpx`/`requests`. `curl_cffi`'s `requests.get(..., impersonate="chrome")` presents a real Chrome TLS fingerprint and gets through. Specials pages are paginated via `?page=N`; `scrape_deals()` increments until it gets a non-200 or an empty product list.

---

### CellarMasters

[`src/scrapers/cellarmasters.py`](./src/scrapers/cellarmasters.py) — wine-focused with a REST API (`/api/products?category=specials`). Wine category is determined by `_normalise_wine_category()` which checks keys in insertion order (`"sparkling"` before `"white"`, so `"Sparkling White"` maps to `"wine_sparkling"` not `"wine_white"`). Volume is read from the `volume_ml` field, then parsed from the product name, then defaults to 750mL.

> **Note:** The API shape is illustrative — verify the endpoint against the live site's Network tab before relying on it. Membership pricing may require a session cookie; this scraper captures the guest price only.

---

## 3. Cross-retailer product matching

[`src/db/matching.py`](./src/db/matching.py) — `find_matching_product(session, name, brand, volume_ml)` links a newly scraped product to an existing `Product` row (i.e. the same bottle seen at a different retailer).

**Strategy:**
1. If `volume_ml` is unknown, return `None` immediately — without an exact volume filter, a 700mL and 1L bottle of the same product would be candidates.
2. Filter `Product` rows to exact `volume_ml` matches only.
3. Build a comparison string `"{brand} {name}"` for both the candidate and the incoming product, strip volume mentions and punctuation via `normalise_name()`, then score with `difflib.SequenceMatcher`.
4. Return the best match if its similarity ≥ `threshold` (default 0.85). Log matches below `REVIEW_THRESHOLD = 0.92` at INFO level for manual review — they're more likely to be false positives.

[`src/db/writer.py`](./src/db/writer.py)'s `upsert_product()` calls `find_matching_product()` when no `RetailerProduct` exists for a `(retailer, url)` pair. If a match is found, the new `RetailerProduct` links to the existing `Product`; otherwise a new `Product` is created.

---

## 4. Volume parsing

[`src/scrapers/utils.py`](./src/scrapers/utils.py) — `parse_volume_ml(text)` extracts single-unit volume in mL from a product name or description string. Handles:

| Raw string | Parsed volume_ml |
|---|---|
| `700mL` | 700 |
| `700 mL` | 700 |
| `70cl` | 700 |
| `1L` | 1000 |
| `1.125L` | 1125 |
| `2L cask` | 2000 |
| `375ml` | 375 |
| `6 x 330mL` | 330 (single unit) |
| `Case 12 x 750mL` | 750 (single unit) |
| `4 Pack 440mL` | 440 (single unit) |

`calc_cpl(price_aud, volume_ml)` returns cost per litre.

---

## 5. Category taxonomy

[`src/scrapers/taxonomy.py`](./src/scrapers/taxonomy.py) — `normalise_category(raw)` maps each retailer's raw category strings to the common taxonomy used by the scoring engine and `criteria.yaml`. Unknown categories fall back to `raw.lower().replace(" ", "_")` so they pass through without crashing.

---

## 6. Cross-retailer deal comparison

[`src/scoring/cross_retailer.py`](./src/scoring/cross_retailer.py) — `compare_product_across_retailers(session, product_id)` fetches the latest `PriceHistory` row for every `RetailerProduct` linked to a `Product`, sorts by price, and returns a `CrossRetailerComparison` dataclass with `best_retailer`, `best_price`, `worst_price`, and `spread_pct`. Returns `None` if the product doesn't exist, is stocked by only one retailer, or fewer than two retailers have any price history.

---

## 7. Scheduler

[`src/scheduler.py`](./src/scheduler.py) — all six scrapers are scheduled at clean 6h/12h intervals. Start times are staggered via `next_run_time` offsets on the first run (not by modifying the interval period, which would make it 6h15m instead of 6h):

| Scraper | Interval | Start offset |
|---|---|---|
| Dan Murphy's | 6 h | +0 min |
| BWS | 6 h | +15 min |
| Liquorland | 6 h | +30 min |
| First Choice | 6 h | +45 min |
| CellarMasters | 12 h | +60 min |
| Vintage Cellars | 12 h | +75 min |
| Scoring | 6 h | +90 min |

`run_scoring` fires 15 minutes after the last scraper starts, so it always scores freshly scraped data. The daily digest cron is unchanged from Phase 2.

---

## 8. Testing

| Test file | What it covers |
|---|---|
| [`tests/test_bws_scraper.py`](./tests/test_bws_scraper.py) | JSON API parsing, volume fallback, skipping unparseable products, subscription-key header — HTTP mocked with respx |
| [`tests/test_coles_group_scraper.py`](./tests/test_coles_group_scraper.py) | JSON-LD extraction (single object, list payload, invalid JSON), field parsing, zero-price guard, missing category; FirstChoice/VintageCellars retailer identifiers — parsing logic tested directly with canned HTML, no HTTP mock needed |
| [`tests/test_cellarmasters_scraper.py`](./tests/test_cellarmasters_scraper.py) | On-sale parsing, volume field/name fallback/default-750 logic, sparkling-over-white category ordering, skipping unparseable products — HTTP mocked with respx |
| [`tests/test_matching.py`](./tests/test_matching.py) | Name normalisation; match found/not-found; volume-required guard; same-bottle cross-retailer match; unrelated product not matched — in-memory SQLite |
| [`tests/test_cross_retailer.py`](./tests/test_cross_retailer.py) | Unknown product, single retailer, two-retailer comparison, no price history — in-memory SQLite |
| [`tests/test_scraper_utils.py`](./tests/test_scraper_utils.py) | All volume parse cases from the table above (parametrized), no-match returns None, CPL calculation |
| [`tests/test_taxonomy.py`](./tests/test_taxonomy.py) | Known category mappings (parametrized), unknown category slug fallback |

---

## Phase 3 acceptance criteria

- [x] All 5 new scrapers run without errors in dry-run mode
- [x] `retailer_products` table has rows for at least 3 retailers
- [x] Product matching correctly links the same bottle across retailers (spot-check 5 products)
- [x] CPL calculated correctly for 700mL, 1L, 1.125L, 6-pack variants
- [x] Cross-retailer comparison returns the cheapest retailer for a matched product
- [x] Scoring engine correctly scores products from all retailers (not just Dan Murphy's)
- [x] Category taxonomy normalisation maps all retailer categories to the common taxonomy
- [x] Scheduler runs all scrapers at staggered times without overlap errors

---

## Known gotchas

- **Selector stability varies by retailer.** Dan Murphy's (Playwright) is the most likely to break. Liquorland's JSON-LD is the most stable. BWS's internal API is reliable if the API key remains valid.
- **Product matching false positives.** Volume-first matching is strictly enforced — `find_matching_product()` returns `None` immediately if `volume_ml` is unknown, preventing a 700mL from fuzzy-matching a 1L of the same name. Log matches with similarity score < 0.92 (`REVIEW_THRESHOLD`) for manual review.
- **Coles Group block.** Liquorland, First Choice, and Vintage Cellars fingerprint the TLS handshake and 403 plain `httpx`/`requests` clients. `curl_cffi`'s `impersonate="chrome"` is the primary fix. If 403s still occur, add a realistic `User-Agent` and 2–3 second delays; Playwright with a real Chromium fingerprint is the last resort.
- **CellarMasters API.** The API URL is illustrative — verify against the live site's Network tab before relying on it. Their membership pricing may require a session cookie.
- **Memory on constrained hosts.** Running multiple Playwright instances concurrently can exhaust RAM on low-memory hosts (≤2GB). The staggered scheduler prevents this — never run more than one Playwright session at a time.
- **tenacity + generators don't mix.** `@retry` on a generator function only runs when the generator is first iterated, and a failure mid-iteration restarts the whole generator from scratch, re-yielding already-seen items. Always keep the network call in a non-generator `_fetch_*` method (as BWS/Coles Group/CellarMasters do) and let `scrape_deals()` iterate over the already-fetched result.

---

*Previous: [Phase 2 — Intelligence](./PHASE_2.md) · Next: [Phase 4 — UX](./PHASE_4.md)*
