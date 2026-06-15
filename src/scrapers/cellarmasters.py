"""
CellarMasters has a REST-ish product API used by their own SPA.
Endpoint: https://www.cellarmasters.com.au/api/products?category=specials
Returns JSON with a product list.

Note: this API shape is illustrative — verify against the live site's
Network tab before relying on it. Membership pricing may require a session
cookie; this scraper only captures the guest price.
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseScraper, ScrapedProduct
from .utils import parse_volume_ml

API_URL = "https://www.cellarmasters.com.au/api/products"

# Order matters: more specific terms first, so e.g. "Sparkling White" matches
# "sparkling" rather than "white".
_WINE_TYPE_MAP = {
    "sparkling": "wine_sparkling",
    "rose": "wine_rose",
    "red": "wine_red",
    "white": "wine_white",
}


class CellarMastersScraper(BaseScraper):
    retailer = "cellarmasters"

    def _normalise_wine_category(self, raw_type: str) -> str:
        raw = raw_type.lower()
        for key, category in _WINE_TYPE_MAP.items():
            if key in raw:
                return category
        return "wine"

    def _parse_api_product(self, item: dict) -> ScrapedProduct | None:
        try:
            volume_ml = item.get("volume_ml") or parse_volume_ml(item.get("name", "")) or 750
            was_price = item.get("was_price")

            return ScrapedProduct(
                retailer=self.retailer,
                retailer_sku=str(item.get("id", "")),
                url=f"https://www.cellarmasters.com.au{item.get('url', '')}",
                name=item.get("name", ""),
                brand=item.get("winery"),
                category=self._normalise_wine_category(item.get("type", "")),
                volume_ml=int(volume_ml),
                abv=item.get("abv"),
                price_aud=float(item.get("price", 0)),
                was_price_aud=float(was_price) if was_price else None,
                in_stock=item.get("in_stock", True),
                on_sale=bool(was_price),
                promo_label=item.get("promo"),
                image_url=item.get("image"),
            )
        except Exception:
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_deals(self) -> list[dict]:
        resp = httpx.get(API_URL, params={"category": "specials", "limit": 200}, timeout=20)
        resp.raise_for_status()
        return resp.json().get("products", [])

    def scrape_deals(self):
        for item in self._fetch_deals():
            p = self._parse_api_product(item)
            if p:
                yield p
