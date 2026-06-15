from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, PriceHistory, Product, RetailerProduct
from src.scoring.cross_retailer import compare_product_across_retailers


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _add_price(session, rp, price_aud, on_sale=False):
    session.add(PriceHistory(
        retailer_product_id=rp.id, price_aud=price_aud, on_sale=on_sale,
        scraped_at=datetime.utcnow(),
    ))
    session.flush()


def test_returns_none_for_unknown_product(session):
    assert compare_product_across_retailers(session, 999) is None


def test_returns_none_when_only_one_retailer_stocks_it(session):
    product = Product(name="Penfolds Bin 389", brand="Penfolds", volume_ml=750)
    session.add(product)
    session.flush()

    rp = RetailerProduct(product_id=product.id, retailer="danmurphys", url="https://dm/p/1")
    session.add(rp)
    session.flush()
    _add_price(session, rp, 55.0)
    session.commit()

    assert compare_product_across_retailers(session, product.id) is None


def test_compares_prices_across_retailers(session):
    product = Product(name="Penfolds Bin 389", brand="Penfolds", volume_ml=750)
    session.add(product)
    session.flush()

    rp_dm = RetailerProduct(product_id=product.id, retailer="danmurphys", url="https://dm/p/1")
    rp_bws = RetailerProduct(product_id=product.id, retailer="bws", url="https://bws/p/1")
    session.add_all([rp_dm, rp_bws])
    session.flush()

    _add_price(session, rp_dm, 60.0, on_sale=False)
    _add_price(session, rp_bws, 50.0, on_sale=True)
    session.commit()

    result = compare_product_across_retailers(session, product.id)

    assert result is not None
    assert result.product_name == "Penfolds Bin 389"
    assert result.volume_ml == 750
    assert result.best_retailer == "bws"
    assert result.best_price == 50.0
    assert result.worst_price == 60.0
    assert result.spread_pct == pytest.approx(16.7, abs=0.1)
    assert [p["retailer"] for p in result.prices] == ["bws", "danmurphys"]


def test_returns_none_when_no_retailer_has_price_history(session):
    product = Product(name="Penfolds Bin 389", brand="Penfolds", volume_ml=750)
    session.add(product)
    session.flush()

    rp_dm = RetailerProduct(product_id=product.id, retailer="danmurphys", url="https://dm/p/1")
    rp_bws = RetailerProduct(product_id=product.id, retailer="bws", url="https://bws/p/1")
    session.add_all([rp_dm, rp_bws])
    session.commit()

    assert compare_product_across_retailers(session, product.id) is None
