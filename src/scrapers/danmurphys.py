import re
from collections.abc import Iterator

from playwright.sync_api import Page, sync_playwright
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseScraper, ScrapedProduct

DEALS_URL = "https://www.danmurphys.com.au/dm/page/deals"
CATEGORY_URLS = {
    "whisky": "https://www.danmurphys.com.au/spirits/whisky",
    "wine_red": "https://www.danmurphys.com.au/wine/red-wine",
    "beer": "https://www.danmurphys.com.au/beer",
    "gin": "https://www.danmurphys.com.au/spirits/gin",
}


class DanMurphysScraper(BaseScraper):
    retailer = "danmurphys"

    def _parse_product_card(self, card) -> ScrapedProduct | None:
        try:
            name = card.query_selector("[data-testid='product-name']").inner_text().strip()
            price_text = card.query_selector("[data-testid='product-price']").inner_text()
            price_aud = float(re.sub(r"[^\d.]", "", price_text))

            was_el = card.query_selector("[data-testid='product-was-price']")
            was_price = float(re.sub(r"[^\d.]", "", was_el.inner_text())) if was_el else None

            url_el = card.query_selector("a[href]")
            url = "https://www.danmurphys.com.au" + url_el.get_attribute("href") if url_el else ""

            promo_el = card.query_selector("[data-testid='product-promo-label']")
            promo_label = promo_el.inner_text().strip() if promo_el else None

            img_el = card.query_selector("img")
            image_url = img_el.get_attribute("src") if img_el else None

            # Extract volume from name (e.g. "700mL", "1.125L")
            vol_match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|mL|L|l)", name)
            volume_ml = None
            if vol_match:
                val, unit = float(vol_match.group(1)), vol_match.group(2).lower()
                volume_ml = int(val * 1000 if unit == "l" else val)

            return ScrapedProduct(
                retailer=self.retailer,
                retailer_sku=url.split("/")[-1] if url else "",
                url=url,
                name=name,
                brand=None,  # Phase 3: extract from name or API
                category=None,  # Phase 3: map from URL path
                volume_ml=volume_ml,
                abv=None,
                price_aud=price_aud,
                was_price_aud=was_price,
                in_stock=True,
                on_sale=was_price is not None,
                promo_label=promo_label,
                image_url=image_url,
            )
        except Exception:
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _goto(self, page: Page, url: str):
        """Navigate with retries — Dan Murphy's occasionally times out under load."""
        page.goto(url, wait_until="networkidle", timeout=30000)

    def _scrape_page(self, page: Page, url: str) -> Iterator[ScrapedProduct]:
        self._goto(page, url)
        # Scroll to load lazy content
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(800)

        cards = page.query_selector_all("[data-testid='product-card']")
        for card in cards:
            product = self._parse_product_card(card)
            if product:
                yield product

        # Pagination: click "Load more" if present
        load_more = page.query_selector("[data-testid='load-more-button']")
        if load_more:
            load_more.click()
            page.wait_for_timeout(1500)
            yield from self._scrape_page(page, page.url)

    def scrape_deals(self) -> Iterator[ScrapedProduct]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"Accept-Language": "en-AU"})
            yield from self._scrape_page(page, DEALS_URL)
            browser.close()

    def scrape_category(self, category: str) -> Iterator[ScrapedProduct]:
        url = CATEGORY_URLS.get(category)
        if not url:
            raise ValueError(f"Unknown category: {category}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            yield from self._scrape_page(page, url)
            browser.close()
