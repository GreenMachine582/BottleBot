"""
BWS uses a GraphQL-style internal API at:
  https://api.bws.com.au/apis/ui/v3/Products/Category/...
This is more stable than scraping rendered HTML and returns structured JSON.
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config.settings import Settings
from .base import BaseScraper, ScrapedProduct
from .taxonomy import normalise_category
from .utils import parse_volume_ml

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
            if not volume_ml:
                volume_ml = parse_volume_ml(item.get("Description", ""))

            return ScrapedProduct(
                retailer=self.retailer,
                retailer_sku=str(item.get("Stockcode", "")),
                url=f"https://bws.com.au/product/{item.get('UrlFriendlyName', '')}",
                name=item.get("Description", ""),
                brand=item.get("Brand"),
                category=normalise_category(item.get("SubType", "")),
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
