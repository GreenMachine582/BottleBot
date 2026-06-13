import logging
import os
import re
from collections.abc import Iterator

from playwright.sync_api import Browser, Page, sync_playwright
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseScraper, ScrapedProduct

log = logging.getLogger(__name__)

DEALS_URL = "https://www.danmurphys.com.au/current-offers"
CATEGORY_URLS = {
    "whisky": "https://www.danmurphys.com.au/whisky/all",
    "wine_red": "https://www.danmurphys.com.au/red-wine/all",
    "beer": "https://www.danmurphys.com.au/beer/all",
    "gin": "https://www.danmurphys.com.au/spirits/gin",
}

# A realistic desktop UA + locale/viewport keeps headless Chromium from tripping
# Cloudflare's bot challenge ("Attention Required!") on every request.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Hard cap on "Show N more" clicks per scrape — bounds runtime even if the
# load-more button never disappears (e.g. it stops loading new cards but stays
# visible/clickable).
MAX_LOAD_MORE_PAGES = 15

PRICE_RE = re.compile(r"[\d,]+(?:\.\d+)?")
VOLUME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|L|l)\b")
SKU_RE = re.compile(r"/product/([^/?]+)")

# DM's <img alt> text is " <Name>...<SIZE><UNIT> <long description>". The
# size is usually repeated immediately before the description (e.g. "330ml
# 330ML", "1l 1L", "700ml 700ml") — SIZE_REPEAT_RE catches that and marks
# where the name ends and the description begins. SIZE_TOKEN_RE is a fallback
# for names DM truncated with "..." before a single uppercase "<N>ML"/"<N>L"
# size field.
SIZE_REPEAT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:ml|mL|ML|l|L)\s+(\d+(?:\.\d+)?)\s*(ml|mL|ML|l|L)\b"
)
SIZE_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ML|mL|L)\b")


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    match = PRICE_RE.search(text.replace(",", ""))
    return float(match.group()) if match else None


def _volume_to_ml(num: str, unit: str) -> int:
    val = float(num)
    return int(val * 1000) if unit.lower() == "l" else int(val)


class DanMurphysScraper(BaseScraper):
    retailer = "danmurphys"

    def __init__(self, member: bool | None = None):
        if member is None:
            member = os.environ.get("DANMURPHYS_MEMBER", "false").strip().lower() in (
                "1", "true", "yes",
            )
        self.member = member

    def _new_page(self, browser: Browser) -> Page:
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="en-AU",
            timezone_id="Australia/Sydney",
        )
        page = context.new_page()
        # Ensure no single Playwright call can hang forever — turns a stuck
        # click/evaluate into a TimeoutError that bubbles up to @retry / the
        # scrape_runs error_msg instead of hanging the whole process.
        page.set_default_timeout(20000)
        return page

    def _extract_price_info(self, card) -> tuple[float | None, float | None, str | None]:
        """Returns (price_aud, was_price_aud, promo_label).

        Dan Murphy's renders two different layouts for a `<product-card-view>`:
          - "Member offer" cards (`.product-card-cost.bg-member-color`) show a
            member price plus a separate "Non-Member: $X" reference price.
          - Plain cards (`.price-container`) show the regular per-unit price
            (`[itemprop='price']`) and, on deal pages, an optional multi-buy
            promo price (`.promo-price`, e.g. "OFFER $121.90 for 2 bottles").

        `self.member` (from the `DANMURPHYS_MEMBER` env var) picks which side
        of the member/non-member split becomes `price_aud` vs `was_price_aud`.
        """
        member_box = card.query_selector(".product-card-cost.bg-member-color")
        if member_box:
            price_el = member_box.query_selector(".card-price")
            unit_el = member_box.query_selector(".product-card-unit")
            offer_el = member_box.query_selector(".offer-txt")

            member_price = _parse_price(price_el.inner_text() if price_el else None)
            non_member_el = card.query_selector(".offers-normal-tile .value")
            non_member_price = _parse_price(
                non_member_el.inner_text() if non_member_el else None
            )

            offer_text = (
                re.sub(r"\s+", " ", offer_el.inner_text()).strip() if offer_el else "MEMBER OFFER"
            )
            unit_text = re.sub(r"\s+", " ", unit_el.inner_text()).strip() if unit_el else ""
            promo_label = f"{offer_text} {unit_text}".strip()

            if self.member:
                return member_price, non_member_price, promo_label
            return non_member_price, None, promo_label

        price_container = card.query_selector(".price-container")
        if price_container:
            unit_el = price_container.query_selector("[itemprop='price'] .value")
            price_aud = _parse_price(unit_el.inner_text() if unit_el else None)

            promo_el = price_container.query_selector(".promo-price")
            promo_label = None
            if promo_el:
                promo_label = re.sub(r"\s+", " ", promo_el.inner_text()).strip()

            return price_aud, None, promo_label

        return None, None, None

    def _parse_product_card(self, card) -> ScrapedProduct | None:
        try:
            link_el = card.query_selector("a[href]")
            href = link_el.get_attribute("href") if link_el else None
            if not href:
                return None
            url = "https://www.danmurphys.com.au" + href.split("?")[0]

            # Scope to the product link's image — cards with "New"/"Catalogue
            # Offers" badges have badge `<img alt="product badge">` elements
            # earlier in the DOM that a bare `card.query_selector("img")`
            # would match instead.
            img_el = link_el.query_selector("img")
            alt = (img_el.get_attribute("alt") or "") if img_el else ""
            image_url = img_el.get_attribute("src") if img_el else None

            # alt text looks like " Name part one<br>Name part two... 700ML <description>"
            # or, for products sized in litres, "...Whiskey 1l 1L <description>"
            # (the size is repeated immediately before the description, in
            # whatever case DM happened to generate).
            repeat_match = SIZE_REPEAT_RE.search(alt)
            if repeat_match and repeat_match.group(1) == repeat_match.group(2):
                name_part = alt[: repeat_match.start(2)]
                volume_ml = _volume_to_ml(repeat_match.group(2), repeat_match.group(3))
            else:
                size_match = SIZE_TOKEN_RE.search(alt)
                if size_match:
                    name_part = alt[: size_match.start()]
                    volume_ml = _volume_to_ml(size_match.group(1), size_match.group(2))
                else:
                    name_part = alt.split("...")[0]
                    volume_ml = None
                    vol_match = VOLUME_RE.search(name_part)
                    if vol_match:
                        volume_ml = _volume_to_ml(vol_match.group(1), vol_match.group(2))

            name = re.sub(r"<br\s*/?>", " ", name_part, flags=re.I)
            name = re.sub(r"\.\.\.\s*$", "", name)
            name = re.sub(r"\s+", " ", name).strip()

            sku_match = SKU_RE.search(href)
            retailer_sku = sku_match.group(1) if sku_match else url.rsplit("/", 1)[-1]

            price_aud, was_price_aud, promo_label = self._extract_price_info(card)
            if price_aud is None:
                return None

            return ScrapedProduct(
                retailer=self.retailer,
                retailer_sku=retailer_sku,
                url=url,
                name=name,
                brand=None,  # Phase 3: extract from name or API
                category=None,  # Phase 3: map from URL path
                volume_ml=volume_ml,
                abv=None,
                price_aud=price_aud,
                was_price_aud=was_price_aud,
                in_stock=True,
                on_sale=was_price_aud is not None or promo_label is not None,
                promo_label=promo_label,
                image_url=image_url,
            )
        except Exception:
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _goto(self, page: Page, url: str):
        """Navigate with retries — Dan Murphy's occasionally times out, or
        serves a Cloudflare challenge page, under load."""
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        if "cloudflare" in page.title().lower():
            raise RuntimeError(f"Blocked by Cloudflare challenge: {url}")

    def _scrape_page(self, page: Page, url: str) -> Iterator[ScrapedProduct]:
        self._goto(page, url)
        yield from self._extract_cards(page)

    def _extract_cards(self, page: Page) -> Iterator[ScrapedProduct]:
        seen = 0
        for page_num in range(MAX_LOAD_MORE_PAGES):
            # Scroll to load lazy content
            for _ in range(5):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(800)

            cards = page.query_selector_all("product-card-view")
            log.info("danmurphys: page %d — %d cards total", page_num, len(cards))
            for card in cards[seen:]:
                product = self._parse_product_card(card)
                if product:
                    yield product

            # Pagination: "Show N more" appends cards to the same page (infinite
            # scroll) — click it and process only the newly-added cards.
            # Re-navigating here (e.g. page.goto(page.url)) would reload from
            # scratch, re-yielding the same products and risking a fresh
            # Cloudflare challenge.
            load_more = page.query_selector(".infinite-loader__load-more-button")
            if not load_more or len(cards) <= seen:
                break
            seen = len(cards)
            load_more.click()
            page.wait_for_timeout(1500)

    def scrape_deals(self) -> Iterator[ScrapedProduct]:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, args=["--disable-blink-features=AutomationControlled"]
            )
            page = self._new_page(browser)
            yield from self._scrape_page(page, DEALS_URL)
            browser.close()

    def scrape_category(self, category: str) -> Iterator[ScrapedProduct]:
        url = CATEGORY_URLS.get(category)
        if not url:
            raise ValueError(f"Unknown category: {category}")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, args=["--disable-blink-features=AutomationControlled"]
            )
            page = self._new_page(browser)
            yield from self._scrape_page(page, url)
            browser.close()
