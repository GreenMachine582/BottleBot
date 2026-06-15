"""
Shared scraper for Coles Group liquor properties (Liquorland, First Choice
Liquor, Vintage Cellars). All three run near-identical storefronts: specials
pages are server-rendered with structured product data in JSON-LD
<script type="application/ld+json"> tags, so we parse those rather than
fighting with CSS selectors.

Coles Group fronts its sites with bot detection that fingerprints the
TLS/JA3 handshake of generic HTTP clients. Plain httpx/requests get 403'd;
curl_cffi impersonates a real Chrome TLS fingerprint and gets through.

Subclasses only need to set `retailer` and `DEALS_URL`.
"""
import json

from bs4 import BeautifulSoup
from curl_cffi import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseScraper, ScrapedProduct
from .taxonomy import normalise_category
from .utils import parse_volume_ml


class ColesGroupScraper(BaseScraper):
    retailer = ""
    DEALS_URL = ""

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

            category = None
            raw_category = item.get("category")
            if isinstance(raw_category, str) and raw_category:
                category = normalise_category(raw_category)

            return ScrapedProduct(
                retailer=self.retailer,
                retailer_sku=item.get("sku", ""),
                url=url,
                name=name,
                brand=item.get("brand", {}).get("name"),
                category=category,
                volume_ml=parse_volume_ml(name),
                abv=None,
                price_aud=price,
                was_price_aud=None,
                in_stock=offers.get("availability", "").endswith("InStock"),
                on_sale=False,  # Set by page context in scrape_deals()
                promo_label=None,
                image_url=item.get("image"),
            )
        except Exception:
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_page(self, page: int):
        return requests.get(f"{self.DEALS_URL}?page={page}", impersonate="chrome", timeout=20)

    def scrape_deals(self):
        # Specials pages use pagination via a "page" query param.
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
