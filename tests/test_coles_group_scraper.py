import json

from src.scrapers.firstchoice import FirstChoiceScraper
from src.scrapers.liquorland import LiquorlandScraper
from src.scrapers.vintagecellars import VintageCellarsScraper

PRODUCT_JSON_LD = {
    "@context": "https://schema.org",
    "@type": "Product",
    "sku": "987654",
    "name": "Penfolds Bin 389 Cabernet Shiraz 750mL",
    "brand": {"@type": "Brand", "name": "Penfolds"},
    "category": "Red Wine",
    "image": "https://example.com/bin389.jpg",
    "offers": {
        "@type": "Offer",
        "price": "45.00",
        "availability": "https://schema.org/InStock",
    },
}


def _html_with_json_ld(*payloads) -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(p)}</script>' for p in payloads
    )
    return f"<html><head>{scripts}</head><body></body></html>"


def test_extract_json_ld_handles_single_object():
    scraper = LiquorlandScraper()
    html = _html_with_json_ld(PRODUCT_JSON_LD)
    results = scraper._extract_json_ld(html)
    assert results == [PRODUCT_JSON_LD]


def test_extract_json_ld_handles_list_payload():
    scraper = LiquorlandScraper()
    html = _html_with_json_ld([PRODUCT_JSON_LD, {"@type": "BreadcrumbList"}])
    results = scraper._extract_json_ld(html)
    assert PRODUCT_JSON_LD in results
    assert any(r.get("@type") == "BreadcrumbList" for r in results)


def test_extract_json_ld_ignores_invalid_json():
    scraper = LiquorlandScraper()
    html = '<html><script type="application/ld+json">{not valid json</script></html>'
    assert scraper._extract_json_ld(html) == []


def test_parse_json_ld_product_extracts_fields():
    scraper = LiquorlandScraper()
    p = scraper._parse_json_ld_product(PRODUCT_JSON_LD, "https://www.liquorland.com.au/p/123")

    assert p is not None
    assert p.retailer == "liquorland"
    assert p.retailer_sku == "987654"
    assert p.name == "Penfolds Bin 389 Cabernet Shiraz 750mL"
    assert p.brand == "Penfolds"
    assert p.category == "wine_red"
    assert p.volume_ml == 750
    assert p.price_aud == 45.0
    assert p.in_stock is True
    assert p.on_sale is False  # set by scrape_deals(), not the parser


def test_parse_json_ld_product_returns_none_for_zero_price():
    item = {**PRODUCT_JSON_LD, "offers": {"price": "0", "availability": "InStock"}}
    scraper = LiquorlandScraper()
    assert scraper._parse_json_ld_product(item, "https://example.com") is None


def test_parse_json_ld_product_handles_missing_category():
    item = {k: v for k, v in PRODUCT_JSON_LD.items() if k != "category"}
    scraper = LiquorlandScraper()
    p = scraper._parse_json_ld_product(item, "https://example.com")
    assert p is not None
    assert p.category is None


def test_firstchoice_and_vintagecellars_share_coles_group_logic():
    assert FirstChoiceScraper.retailer == "firstchoice"
    assert "firstchoiceliquor.com.au" in FirstChoiceScraper.DEALS_URL

    assert VintageCellarsScraper.retailer == "vintagecellars"
    assert "vintagecellars.com.au" in VintageCellarsScraper.DEALS_URL

    # Same parsing logic, just a different retailer/URL.
    item = FirstChoiceScraper()._parse_json_ld_product(PRODUCT_JSON_LD, "https://example.com")
    assert item.retailer == "firstchoice"
