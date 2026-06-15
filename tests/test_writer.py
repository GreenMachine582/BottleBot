import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base
from src.db.writer import upsert_product
from src.scrapers.base import ScrapedProduct


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def make_product(**overrides) -> ScrapedProduct:
    defaults = dict(
        retailer="danmurphys", retailer_sku="123", url="https://example.com/p/123",
        name="Test Whisky 700mL", brand="Test", category="whisky",
        volume_ml=700, abv=40.0, price_aud=50.0, was_price_aud=60.0,
        in_stock=True, on_sale=True, promo_label="Test Sale", image_url=None,
    )
    defaults.update(overrides)
    return ScrapedProduct(**defaults)


def test_first_scrape_inserts_price_history(session):
    rp, changed = upsert_product(session, make_product())
    session.commit()
    assert changed is True
    assert rp.id is not None


def test_unchanged_price_does_not_insert_again(session):
    upsert_product(session, make_product())
    session.commit()
    _, changed = upsert_product(session, make_product())
    session.commit()
    assert changed is False


def test_price_drop_inserts_new_row(session):
    upsert_product(session, make_product(price_aud=50.0))
    session.commit()
    _, changed = upsert_product(session, make_product(price_aud=45.0))
    session.commit()
    assert changed is True


def test_same_bottle_from_different_retailer_links_to_existing_product(session):
    rp1, _ = upsert_product(session, make_product(
        retailer="danmurphys",
        url="https://danmurphys.com.au/p/123",
        name="Test Whisky 700mL",
        brand="Test",
        volume_ml=700,
    ))
    session.commit()

    # Same bottle from BWS, formatted slightly differently.
    rp2, _ = upsert_product(session, make_product(
        retailer="bws",
        url="https://bws.com.au/p/456",
        name="TEST WHISKY, 700ML",
        brand="Test",
        volume_ml=700,
    ))
    session.commit()

    assert rp1.product_id == rp2.product_id


def test_different_volume_creates_separate_product(session):
    rp1, _ = upsert_product(session, make_product(
        retailer="danmurphys",
        url="https://danmurphys.com.au/p/123",
        name="Test Whisky 700mL",
        brand="Test",
        volume_ml=700,
    ))
    session.commit()

    rp2, _ = upsert_product(session, make_product(
        retailer="bws",
        url="https://bws.com.au/p/789",
        name="Test Whisky 1L",
        brand="Test",
        volume_ml=1000,
    ))
    session.commit()

    assert rp1.product_id != rp2.product_id
