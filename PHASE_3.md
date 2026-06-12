# Phase 3 — Breadth: More Sources & Normalisation

> **Goal:** Expand coverage to BWS, Liquorland, First Choice Liquor, and others. Normalise products across retailers so the same bottle can be compared cross-site, and introduce robust CPL (cost per litre) calculations as the primary comparison metric.

**Estimated effort:** 2–3 weekends  
**Depends on:** Phase 1 (scraper architecture), Phase 2 (scoring pipeline)  
**Unlocks:** Phase 4 (cross-retailer comparison in the UI)

---

## Deliverables

- [ ] BWS scraper, with tenacity retries and its subscription key loaded from `.env` via `Settings`
- [ ] Liquorland scraper, using curl_cffi to avoid Coles Group's TLS-fingerprint bot detection
- [ ] First Choice Liquor scraper (same curl_cffi pattern as Liquorland)
- [ ] CellarMasters scraper (wine focus)
- [ ] Vintage Cellars scraper
- [ ] Cross-retailer product deduplication / matching
- [ ] Category taxonomy normalisation (each site uses different names)
- [ ] Robust CPL calculation with volume parsing edge cases
- [ ] Cross-retailer deal comparison (same product, cheapest retailer wins)
- [ ] Scheduler updated for all sources with staggered timing
- [ ] respx-based tests for the new HTTP API scrapers

---

## 1. Scraper architecture review

Phase 1 established `BaseScraper`. All new scrapers implement the same interface — the scoring engine doesn't care which retailer a product came from.

```
src/scrapers/
├── base.py              ✅ Phase 1
├── danmurphys.py        ✅ Phase 1
├── bws.py               🆕 Phase 3
├── liquorland.py        🆕 Phase 3
├── firstchoice.py       🆕 Phase 3
├── cellarmasters.py     🆕 Phase 3
└── vintagecellars.py    🆕 Phase 3
```

Each scraper only needs to implement `scrape_deals()` and optionally `scrape_category()`. The persistence layer, scoring, and alerting are unchanged.

---

## 2. Retailer scraper notes

### BWS

BWS shares the Endeavour Group backend with Dan Murphy's. The product catalogue overlaps significantly, but pricing and promotions differ. BWS also has an unofficial internal API used by its own frontend — intercepting this is more reliable than scraping rendered HTML.

```python
# src/scrapers/bws.py
"""
BWS uses a GraphQL-style internal API at:
  https://api.bws.com.au/apis/ui/v3/Products/Category/...
This is more stable than scraping rendered HTML and returns structured JSON.
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import BaseScraper, ScrapedProduct
from ..config.settings import Settings

BWS_API_BASE = "https://api.bws.com.au/apis/ui/v3"
BWS_DEALS_URL = f"{BWS_API_BASE}/Products/Category/specials?pageNumber=1&pageSize=100"

class BWSScraper(BaseScraper):
    retailer = "bws"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def _headers(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (compatible; BottleBot/1.0)",
            "referer": "https://bws.com.au/",
            "subscription-key": self.settings.bws_subscription_key,
        }

    def _parse_api_product(self, item: dict) -> ScrapedProduct | None:
        try:
            price = item.get("Price", {})
            current = price.get("PromotionalPrice") or price.get("Value")
            was = price.get("Value") if price.get("PromotionalPrice") else None
            volume_ml = item.get("PackageSize", {}).get("Millilitres")

            return ScrapedProduct(
                retailer=self.retailer,
                retailer_sku=str(item.get("Stockcode", "")),
                url=f"https://bws.com.au/product/{item.get('UrlFriendlyName', '')}",
                name=item.get("Description", ""),
                brand=item.get("Brand"),
                category=self._normalise_category(item.get("SubType", "")),
                volume_ml=volume_ml,
                abv=item.get("AlcoholPercentage"),
                price_aud=float(current),
                was_price_aud=float(was) if was else None,
                in_stock=item.get("InStoreAvailability", True),
                on_sale=price.get("PromotionalPrice") is not None,
                promo_label=item.get("Tags", [None])[0],
                image_url=item.get("SmallImageFile"),
            )
        except Exception:
            return None

    def _normalise_category(self, bws_category: str) -> str:
        mapping = {
            "scotch whisky": "whisky", "bourbon": "whisky", "irish whiskey": "whisky",
            "red wine": "wine_red", "white wine": "wine_white", "sparkling": "wine_sparkling",
            "craft beer": "beer", "lager": "beer",
            "gin": "gin", "vodka": "vodka", "rum": "rum",
        }
        return mapping.get(bws_category.lower(), bws_category.lower().replace(" ", "_"))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_deals(self) -> list[dict]:
        resp = httpx.get(BWS_DEALS_URL, headers=self._headers(), timeout=20)
        resp.raise_for_status()
        return resp.json().get("Products", [])

    def scrape_deals(self):
        for item in self._fetch_deals():
            p = self._parse_api_product(item)
            if p:
                yield p
```

> **API key note:** BWS's internal API may require a `subscription-key` header extracted from their frontend JS bundle. Check the Network tab when browsing bws.com.au — look for requests to `api.bws.com.au`. This key changes infrequently. Add it to `.env` as `BOTTLEBOT_BWS_SUBSCRIPTION_KEY` and extend the `Settings` class from Phase 2 with a matching `bws_subscription_key: str = ""` field — never commit it to `criteria.yaml`.

---

### Liquorland & First Choice (Coles Group)

Both are Coles Group properties and run similar infrastructure. Liquorland uses a more standard rendered HTML structure than BWS.

```python
# src/scrapers/liquorland.py
"""
Liquorland is a Coles Group property. Product pages are server-rendered
with structured data in JSON-LD <script> tags — parse these rather than
fighting with CSS selectors.

Coles Group fronts its sites with bot detection that fingerprints the
TLS/JA3 handshake of generic HTTP clients. Plain httpx/requests get 403'd;
curl_cffi impersonates a real Chrome TLS fingerprint and gets through.
"""
from curl_cffi import requests
import json
import re
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import BaseScraper, ScrapedProduct

DEALS_URL = "https://www.liquorland.com.au/specials"

class LiquorlandScraper(BaseScraper):
    retailer = "liquorland"

    def _extract_json_ld(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict):
                    results.append(data)
            except Exception:
                pass
        return results

    def _parse_json_ld_product(self, item: dict, url: str) -> ScrapedProduct | None:
        try:
            offers = item.get("offers", {})
            price = float(offers.get("price", 0))
            if not price:
                return None
            name = item.get("name", "")
            vol_match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|mL|L)", name)
            volume_ml = None
            if vol_match:
                val, unit = float(vol_match.group(1)), vol_match.group(2)
                volume_ml = int(val * 1000 if unit == "L" else val)

            return ScrapedProduct(
                retailer=self.retailer,
                retailer_sku=item.get("sku", ""),
                url=url,
                name=name,
                brand=item.get("brand", {}).get("name"),
                category=None,   # Extracted from page context separately
                volume_ml=volume_ml,
                abv=None,
                price_aud=price,
                was_price_aud=None,
                in_stock=offers.get("availability", "").endswith("InStock"),
                on_sale=False,   # Set by page context
                promo_label=None,
                image_url=item.get("image"),
            )
        except Exception:
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_page(self, page: int):
        return requests.get(f"{DEALS_URL}?page={page}", impersonate="chrome", timeout=20)

    def scrape_deals(self):
        # Liquorland specials page uses pagination via query param
        page = 1
        while True:
            resp = self._fetch_page(page)
            if resp.status_code != 200:
                break
            items = self._extract_json_ld(resp.text)
            products = [i for i in items if i.get("@type") == "Product"]
            if not products:
                break
            for item in products:
                p = self._parse_json_ld_product(item, str(resp.url))
                if p:
                    p.on_sale = True
                    yield p
            page += 1
```

> First Choice Liquor follows an almost identical pattern — create `firstchoice.py` by copying `liquorland.py` and updating `DEALS_URL` and `retailer = "firstchoice"`.

---

### CellarMasters

CellarMasters is wine-focused with a membership pricing tier. Scrape both guest and member prices where available.

```python
# src/scrapers/cellarmasters.py
"""
CellarMasters has a REST-ish product API used by their own SPA.
Endpoint: https://www.cellarmasters.com.au/api/products?category=specials
Returns JSON with product list.
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import BaseScraper, ScrapedProduct

API_URL = "https://www.cellarmasters.com.au/api/products"

class CellarMastersScraper(BaseScraper):
    retailer = "cellarmasters"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_deals(self) -> list[dict]:
        resp = httpx.get(API_URL, params={"category": "specials", "limit": 200}, timeout=20)
        resp.raise_for_status()
        return resp.json().get("products", [])

    def scrape_deals(self):
        for item in self._fetch_deals():
            try:
                yield ScrapedProduct(
                    retailer=self.retailer,
                    retailer_sku=str(item.get("id", "")),
                    url=f"https://www.cellarmasters.com.au{item.get('url', '')}",
                    name=item.get("name", ""),
                    brand=item.get("winery"),
                    category="wine_red" if "red" in item.get("type","").lower() else
                              "wine_white" if "white" in item.get("type","").lower() else
                              "wine_sparkling" if "sparkling" in item.get("type","").lower() else
                              "wine",
                    volume_ml=int(item.get("volume_ml", 750)),
                    abv=item.get("abv"),
                    price_aud=float(item.get("price", 0)),
                    was_price_aud=float(item.get("was_price")) if item.get("was_price") else None,
                    in_stock=item.get("in_stock", True),
                    on_sale=bool(item.get("was_price")),
                    promo_label=item.get("promo"),
                    image_url=item.get("image"),
                )
            except Exception:
                continue
```

> **Note:** CellarMasters URL paths and API structure should be verified against the live site — these are illustrative patterns based on common wine retailer API shapes.

---

## 3. Cross-retailer product matching

The same bottle of Johnnie Walker Black 700mL will appear as a separate `RetailerProduct` row for each retailer. We need a way to link them to the same canonical `Product` so we can compare prices across retailers.

### Matching strategy

Match on a normalised key derived from: `brand + name + volume_ml`. This catches ~90% of cases. Fuzzy matching handles spelling variations.

```python
# src/db/matching.py
import re
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from .models import Product, RetailerProduct

def normalise_name(name: str) -> str:
    """Strip volume, punctuation, case for comparison."""
    name = name.lower()
    name = re.sub(r"\b\d+\s*(ml|l|litre|liter)\b", "", name)
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def find_matching_product(
    session: Session,
    name: str,
    brand: str | None,
    volume_ml: int | None,
    threshold: float = 0.85,
) -> Product | None:
    """
    Try to find an existing Product that matches the incoming scraped product.
    Uses exact volume match + fuzzy name similarity.
    """
    candidates = session.query(Product)
    if volume_ml:
        candidates = candidates.filter(Product.volume_ml == volume_ml)
    candidates = candidates.all()

    norm_name = normalise_name(name)
    best_score = 0.0
    best_match = None

    for candidate in candidates:
        cand_norm = normalise_name(candidate.name)
        similarity = SequenceMatcher(None, norm_name, cand_norm).ratio()
        if similarity > best_score:
            best_score = similarity
            best_match = candidate

    if best_score >= threshold:
        return best_match
    return None
```

Update `upsert_product` in Phase 1's writer to use `find_matching_product` before creating a new `Product` row.

---

## 4. Volume parsing edge cases

Real-world volume strings seen in Australian bottle shop listings:

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

```python
# src/scrapers/utils.py
import re

_VOL_RE = re.compile(
    r"(?:case\s+\d+\s+x\s+|(\d+)\s+(?:pack|x)\s+)?(\d+(?:\.\d+)?)\s*(ml|mL|cl|cL|l|L)",
    re.IGNORECASE
)

def parse_volume_ml(text: str) -> int | None:
    """
    Extract single-unit volume in mL from a product name string.
    Handles packs, cases, cl, L, mL variants.
    Returns None if no volume found.
    """
    match = _VOL_RE.search(text)
    if not match:
        return None
    val = float(match.group(2))
    unit = match.group(3).lower()
    if unit in ("l",):
        return int(val * 1000)
    elif unit in ("cl",):
        return int(val * 10)
    else:
        return int(val)

def calc_cpl(price_aud: float, volume_ml: int) -> float:
    """Cost per litre."""
    return price_aud / (volume_ml / 1000)
```

---

## 5. Category taxonomy normalisation

Each retailer uses different category names. Map all to a common taxonomy used by the scoring engine and the YAML config.

```python
# src/scrapers/taxonomy.py

CATEGORY_MAP: dict[str, str] = {
    # Whisky
    "scotch whisky":      "whisky",
    "scotch":             "whisky",
    "bourbon":            "whisky",
    "american whiskey":   "whisky",
    "irish whiskey":      "whisky",
    "japanese whisky":    "whisky",
    "single malt":        "whisky",
    "blended whisky":     "whisky",
    "tennessee whiskey":  "whisky",

    # Wine
    "red wine":           "wine_red",
    "reds":               "wine_red",
    "white wine":         "wine_white",
    "whites":             "wine_white",
    "sparkling wine":     "wine_sparkling",
    "champagne":          "wine_sparkling",
    "prosecco":           "wine_sparkling",
    "rosé":               "wine_rose",
    "rose":               "wine_rose",
    "fortified":          "wine_fortified",
    "port":               "wine_fortified",

    # Beer
    "beer":               "beer",
    "craft beer":         "beer",
    "lager":              "beer",
    "ale":                "beer",
    "ipa":                "beer",
    "stout":              "beer",
    "cider":              "cider",

    # Spirits
    "gin":                "gin",
    "vodka":              "vodka",
    "rum":                "rum",
    "tequila":            "tequila",
    "brandy":             "brandy",
    "cognac":             "brandy",
    "liqueur":            "liqueur",

    # Other
    "rtd":                "rtd",
    "ready to drink":     "rtd",
    "premix":             "rtd",
}

def normalise_category(raw: str) -> str:
    return CATEGORY_MAP.get(raw.lower().strip(), raw.lower().replace(" ", "_"))
```

---

## 6. Cross-retailer deal comparison

Once the same product is matched across retailers, we can find which retailer has the best current price.

```python
# src/scoring/cross_retailer.py
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..db.models import Product, RetailerProduct, PriceHistory

@dataclass
class CrossRetailerComparison:
    product_id: int
    product_name: str
    volume_ml: int | None
    prices: list[dict]   # [{"retailer": ..., "price": ..., "url": ...}]
    best_retailer: str
    best_price: float
    worst_price: float
    spread_pct: float    # % difference between best and worst

def compare_product_across_retailers(
    session: Session, product_id: int
) -> CrossRetailerComparison | None:
    product = session.get(Product, product_id)
    if not product:
        return None

    rps = session.query(RetailerProduct).filter_by(product_id=product_id).all()
    if len(rps) < 2:
        return None

    prices = []
    for rp in rps:
        latest = (
            session.query(PriceHistory)
            .filter_by(retailer_product_id=rp.id)
            .order_by(PriceHistory.scraped_at.desc())
            .first()
        )
        if latest:
            prices.append({
                "retailer": rp.retailer,
                "price": latest.price_aud,
                "url": rp.url,
                "on_sale": latest.on_sale,
            })

    if not prices:
        return None

    prices.sort(key=lambda p: p["price"])
    best = prices[0]["price"]
    worst = prices[-1]["price"]
    spread = (worst - best) / worst * 100

    return CrossRetailerComparison(
        product_id=product_id,
        product_name=product.name,
        volume_ml=product.volume_ml,
        prices=prices,
        best_retailer=prices[0]["retailer"],
        best_price=best,
        worst_price=worst,
        spread_pct=round(spread, 1),
    )
```

---

## 7. Scheduler update

Stagger scrape times to avoid all retailers being hit simultaneously, and to spread load on the host.

```python
# src/scheduler.py (updated)
scheduler.add_job(run_scraper, "interval", hours=6, minutes=0,  args=[DanMurphysScraper,    "danmurphys"])
scheduler.add_job(run_scraper, "interval", hours=6, minutes=15, args=[BWSScraper,            "bws"])
scheduler.add_job(run_scraper, "interval", hours=6, minutes=30, args=[LiquorlandScraper,     "liquorland"])
scheduler.add_job(run_scraper, "interval", hours=6, minutes=45, args=[FirstChoiceScraper,    "firstchoice"])
scheduler.add_job(run_scraper, "interval", hours=12, minutes=0, args=[CellarMastersScraper,  "cellarmasters"])
scheduler.add_job(run_scraper, "interval", hours=12, minutes=30,args=[VintageCellarsScraper, "vintagecellars"])
```

---

## 8. Testing the new scrapers

The BWS and CellarMasters scrapers talk to JSON APIs over httpx — [respx](https://lundberg.github.io/respx/)
mocks those calls so the parsing logic can be tested without hitting the network.

```python
# tests/test_bws_scraper.py
import respx
import httpx
from src.scrapers.bws import BWSScraper, BWS_DEALS_URL

@respx.mock
def test_scrape_deals_parses_and_normalises():
    respx.get(BWS_DEALS_URL).mock(return_value=httpx.Response(200, json={
        "Products": [{
            "Stockcode": "123456",
            "Description": "Johnnie Walker Black Label 700mL",
            "Brand": "Johnnie Walker",
            "SubType": "scotch whisky",
            "PackageSize": {"Millilitres": 700},
            "AlcoholPercentage": 40.0,
            "Price": {"Value": 65.0, "PromotionalPrice": 52.0},
            "InStoreAvailability": True,
            "Tags": ["EOFY Sale"],
            "UrlFriendlyName": "johnnie-walker-black-label-700ml",
            "SmallImageFile": "jwb700.jpg",
        }]
    }))

    products = list(BWSScraper().scrape_deals())

    assert len(products) == 1
    p = products[0]
    assert p.price_aud == 52.0
    assert p.was_price_aud == 65.0
    assert p.category == "whisky"     # SubType "scotch whisky" normalised via _normalise_category
    assert p.on_sale is True
```

```bash
pytest tests/ -v -k scraper
```

> **curl_cffi scrapers (Liquorland, First Choice) aren't covered by respx** — respx only intercepts
> httpx. Test their parsing logic (`_extract_json_ld`, `_parse_json_ld_product`) directly with
> canned JSON-LD fixtures instead of mocking the HTTP layer.

---

## Phase 3 acceptance criteria

- [ ] All 5 new scrapers run without errors in dry-run mode
- [ ] `retailer_products` table has rows for at least 3 retailers
- [ ] Product matching correctly links the same bottle across retailers (spot-check 5 products)
- [ ] CPL calculated correctly for 700mL, 1L, 1.125L, 6-pack variants
- [ ] Cross-retailer comparison returns the cheapest retailer for a matched product
- [ ] Scoring engine correctly scores products from all retailers (not just Dan Murphy's)
- [ ] Category taxonomy normalisation maps all retailer categories to the common taxonomy
- [ ] Scheduler runs all scrapers at staggered times without overlap errors

---

## Known gotchas

- **Selector stability varies by retailer.** Dan Murphy's (Playwright) is the most likely to break. Liquorland's JSON-LD is the most stable. BWS's internal API is reliable if the API key remains valid.
- **Product matching false positives.** The fuzzy name match might link a 700mL to a 1L if volume parsing fails. Always require volume match before fuzzy name match. Log matches with similarity score < 0.92 for manual review.
- **Coles Group block.** Liquorland and First Choice fingerprint the TLS handshake and 403 plain httpx/requests clients. curl_cffi's `impersonate="chrome"` is the primary fix (see Section 2). If 403s still occur, add a realistic `User-Agent` and 2–3 second delays as a fallback; Playwright with a real Chromium fingerprint is the last resort.
- **CellarMasters API:** The API URL used above is illustrative — verify against the live site's Network tab before relying on it. Their membership pricing may require a session cookie.
- **Memory on constrained hosts:** Running 6 Playwright instances concurrently can exhaust RAM on low-memory hosts (≤2GB). The staggered scheduler prevents this — never run more than one Playwright session at a time.
- **tenacity + generators don't mix.** `@retry` on a generator function only runs when the generator is first iterated, and a failure mid-iteration restarts the whole generator from scratch — re-yielding already-seen items. Keep the network call in a non-generator `_fetch_*` method (as in BWS/Liquorland/CellarMasters above) and let `scrape_deals()` iterate over its already-fetched result.

---

*Previous: [Phase 2 — Intelligence](./PHASE_2.md) · Next: [Phase 4 — UX](./PHASE_4.md)*
