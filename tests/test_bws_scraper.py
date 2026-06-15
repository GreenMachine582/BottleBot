import httpx
import respx

from src.config.settings import Settings
from src.scrapers.bws import BWS_DEALS_URL, BWSScraper


def _settings() -> Settings:
    return Settings(_env_file=None, bws_subscription_key="test-key")


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

    products = list(BWSScraper(_settings()).scrape_deals())

    assert len(products) == 1
    p = products[0]
    assert p.price_aud == 52.0
    assert p.was_price_aud == 65.0
    assert p.category == "whisky"  # SubType "scotch whisky" normalised via taxonomy
    assert p.volume_ml == 700
    assert p.on_sale is True


@respx.mock
def test_scrape_deals_falls_back_to_parsing_volume_from_description():
    respx.get(BWS_DEALS_URL).mock(return_value=httpx.Response(200, json={
        "Products": [{
            "Stockcode": "789",
            "Description": "Some Craft Beer 6 x 330mL",
            "Brand": "Some Brewery",
            "SubType": "craft beer",
            "PackageSize": {},
            "Price": {"Value": 20.0},
            "UrlFriendlyName": "some-craft-beer",
        }]
    }))

    products = list(BWSScraper(_settings()).scrape_deals())

    assert len(products) == 1
    assert products[0].volume_ml == 330
    assert products[0].category == "beer"
    assert products[0].on_sale is False
    assert products[0].was_price_aud is None


@respx.mock
def test_scrape_deals_skips_unparseable_product():
    respx.get(BWS_DEALS_URL).mock(return_value=httpx.Response(200, json={
        "Products": [{"Price": {"Value": "not-a-number"}}]
    }))

    products = list(BWSScraper(_settings()).scrape_deals())

    assert products == []


def test_headers_include_subscription_key():
    headers = BWSScraper(_settings())._headers()
    assert headers["subscription-key"] == "test-key"
