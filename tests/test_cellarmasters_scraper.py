import httpx
import respx

from src.scrapers.cellarmasters import API_URL, CellarMastersScraper


@respx.mock
def test_scrape_deals_parses_wine_on_sale():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json={
        "products": [{
            "id": 555,
            "name": "Penfolds Bin 389 750mL",
            "winery": "Penfolds",
            "type": "Red",
            "volume_ml": 750,
            "abv": 14.5,
            "price": 55.0,
            "was_price": 70.0,
            "url": "/p/penfolds-bin-389",
            "in_stock": True,
            "promo": "Member Special",
            "image": "bin389.jpg",
        }]
    }))

    products = list(CellarMastersScraper().scrape_deals())

    assert len(products) == 1
    p = products[0]
    assert p.retailer == "cellarmasters"
    assert p.url == "https://www.cellarmasters.com.au/p/penfolds-bin-389"
    assert p.category == "wine_red"
    assert p.volume_ml == 750
    assert p.price_aud == 55.0
    assert p.was_price_aud == 70.0
    assert p.on_sale is True


@respx.mock
def test_scrape_deals_defaults_volume_when_missing():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json={
        "products": [{
            "id": 1,
            "name": "Mystery Sparkling",
            "type": "Sparkling White",
            "price": 20.0,
        }]
    }))

    products = list(CellarMastersScraper().scrape_deals())

    assert len(products) == 1
    assert products[0].volume_ml == 750
    assert products[0].category == "wine_sparkling"
    assert products[0].on_sale is False
    assert products[0].was_price_aud is None


@respx.mock
def test_scrape_deals_parses_volume_from_name_when_field_missing():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json={
        "products": [{
            "id": 2,
            "name": "Boutique White 1.5L",
            "type": "White",
            "price": 25.0,
        }]
    }))

    products = list(CellarMastersScraper().scrape_deals())

    assert products[0].volume_ml == 1500
    assert products[0].category == "wine_white"


@respx.mock
def test_scrape_deals_skips_unparseable_product():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json={
        "products": [{"price": "not-a-number"}]
    }))

    assert list(CellarMastersScraper().scrape_deals()) == []
