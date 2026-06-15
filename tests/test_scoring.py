from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, PriceHistory, Product, RetailerProduct
from src.scoring.criteria import Criteria
from src.scoring.engine import ScoringEngine


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def make_criteria(**overrides) -> Criteria:
    """Default criteria with eofy_window_bonus zeroed so tests don't depend
    on whether 'today' happens to fall in a sale window."""
    data = {"scoring": {"modifiers": {"eofy_window_bonus": 0}}, **overrides}
    return Criteria.model_validate(data)


def make_deal(
    session: Session,
    *,
    name="Test Product",
    brand="TestBrand",
    category="beer",
    volume_ml=1000,
    prices: list[tuple[float, int]],
    was_price=None,
    latest_on_sale=True,
) -> tuple[RetailerProduct, PriceHistory]:
    """Create a Product/RetailerProduct with the given (price_aud, days_ago)
    price history. The row with the smallest days_ago is the 'latest'."""
    product = Product(name=name, brand=brand, category=category, volume_ml=volume_ml, abv=40.0)
    session.add(product)
    session.flush()

    rp = RetailerProduct(
        product_id=product.id,
        retailer="danmurphys",
        retailer_sku=name,
        url=f"https://example.com/{name}",
    )
    session.add(rp)
    session.flush()

    now = datetime.utcnow()
    min_days = min(days_ago for _, days_ago in prices)
    latest = None
    for price, days_ago in prices:
        is_latest = days_ago == min_days
        ph = PriceHistory(
            retailer_product_id=rp.id,
            price_aud=price,
            was_price_aud=was_price,
            in_stock=True,
            on_sale=(is_latest and latest_on_sale),
            promo_label="Sale" if is_latest else None,
            scraped_at=now - timedelta(days=days_ago),
        )
        session.add(ph)
        if is_latest:
            latest = ph

    session.flush()
    return rp, latest


def test_min_discount_filter(session):
    rp, latest = make_deal(session, prices=[(100, 10), (90, 0)])
    session.commit()
    result = ScoringEngine(session, make_criteria()).score_deal(rp, latest)
    assert result is None


def test_min_saving_filter(session):
    rp, latest = make_deal(session, prices=[(49, 10), (31, 0)])
    session.commit()
    result = ScoringEngine(session, make_criteria()).score_deal(rp, latest)
    assert result is None


def test_brand_blocklist_filter(session):
    rp, latest = make_deal(session, brand="BlockedBrand", prices=[(60, 10), (20, 0)])
    session.commit()
    criteria = make_criteria(brands={"blocklist": ["BlockedBrand"]})
    result = ScoringEngine(session, criteria).score_deal(rp, latest)
    assert result is None


def test_max_cpl_filter_blocks_overpriced_deal(session):
    rp, latest = make_deal(session, category="whisky", volume_ml=700, prices=[(90, 10), (50, 0)])
    session.commit()
    result = ScoringEngine(session, make_criteria()).score_deal(rp, latest)
    assert result is None  # $71.43/L > default $30/L max


def test_max_cpl_filter_allows_with_custom_threshold(session):
    rp, latest = make_deal(session, category="whisky", volume_ml=700, prices=[(90, 10), (50, 0)])
    session.commit()
    criteria = make_criteria(thresholds={"max_cpl_aud": {"whisky": 100, "default": 30}})
    result = ScoringEngine(session, criteria).score_deal(rp, latest)
    assert result is not None
    assert result.cpl_aud == pytest.approx(50 / 0.7)


def test_full_score_with_new_low_bonus(session):
    rp, latest = make_deal(session, category="beer", volume_ml=1000, prices=[(60, 10), (20, 0)])
    session.commit()
    result = ScoringEngine(session, make_criteria()).score_deal(rp, latest)
    assert result is not None
    assert result.is_watchlist is False
    assert result.is_new_low is True
    assert result.score == 71.7


def test_watchlist_bonus(session):
    rp, latest = make_deal(
        session,
        name="Special Whisky 700mL",
        category="whisky",
        volume_ml=2000,
        prices=[(45, 20), (100, 10), (50, 0)],
    )
    session.commit()
    criteria = make_criteria(watchlist={"products": ["Special Whisky"]})
    result = ScoringEngine(session, criteria).score_deal(rp, latest)
    assert result is not None
    assert result.is_watchlist is True
    assert result.is_new_low is False
    assert result.score == 79.6


def test_score_all_current_deals(session):
    criteria = make_criteria()

    # Score 71.7 (>= 65 threshold) -> included
    make_deal(session, name="Deal A", category="beer", volume_ml=1000, prices=[(60, 10), (20, 0)])

    # Score 42.1 (< 65 threshold) -> excluded
    make_deal(
        session,
        name="Deal B",
        category="wine_red",
        volume_ml=2000,
        prices=[(50, 20), (130, 10), (60, 0)],
    )

    # Never on sale -> excluded entirely
    make_deal(
        session,
        name="Deal C",
        category="beer",
        volume_ml=1000,
        prices=[(10, 0)],
        latest_on_sale=False,
    )

    # Score 86.1 -> included, ranked above Deal A
    make_deal(session, name="Deal D", category="gin", volume_ml=1500, prices=[(100, 10), (40, 0)])

    session.commit()

    deals = ScoringEngine(session, criteria).score_all_current_deals()

    assert [d.product_name for d in deals] == ["Deal D", "Deal A"]
    assert deals[0].score == 86.1
    assert deals[1].score == 71.7


def test_eofy_window_bonus_applied_when_in_sale_window(session, monkeypatch):
    rp, latest = make_deal(session, category="beer", volume_ml=1000, prices=[(60, 10), (20, 0)])
    session.commit()

    monkeypatch.setattr(ScoringEngine, "_in_sale_window", lambda self: True)
    result = ScoringEngine(session, Criteria()).score_deal(rp, latest)

    assert result is not None
    assert result.score == 81.7  # 71.7 base+new_low, +10 eofy_window_bonus
    assert result.score_breakdown["modifiers"] == 25.0


def test_eofy_window_bonus_not_applied_outside_sale_window(session, monkeypatch):
    rp, latest = make_deal(session, category="beer", volume_ml=1000, prices=[(60, 10), (20, 0)])
    session.commit()

    monkeypatch.setattr(ScoringEngine, "_in_sale_window", lambda self: False)
    result = ScoringEngine(session, Criteria()).score_deal(rp, latest)

    assert result is not None
    assert result.score == 71.7
    assert result.score_breakdown["modifiers"] == 15.0
