from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..db.models import PriceHistory, Product, RetailerProduct


@dataclass
class CrossRetailerComparison:
    product_id: int
    product_name: str
    volume_ml: int | None
    prices: list[dict]  # [{"retailer": ..., "price": ..., "url": ..., "on_sale": ...}]
    best_retailer: str
    best_price: float
    worst_price: float
    spread_pct: float  # % difference between best and worst


def compare_product_across_retailers(
    session: Session, product_id: int
) -> CrossRetailerComparison | None:
    """
    Compare the latest price for `product_id` across every retailer that
    stocks it. Returns None if the product doesn't exist or is only stocked
    by a single retailer (nothing to compare).
    """
    product = session.get(Product, product_id)
    if not product:
        return None

    rps = session.query(RetailerProduct).filter_by(product_id=product_id).all()
    if len(rps) < 2:
        return None

    prices = []
    for rp in rps:
        latest = (
            session.query(PriceHistory)
            .filter_by(retailer_product_id=rp.id)
            .order_by(PriceHistory.scraped_at.desc())
            .first()
        )
        if latest:
            prices.append({
                "retailer": rp.retailer,
                "price": latest.price_aud,
                "url": rp.url,
                "on_sale": latest.on_sale,
            })

    if len(prices) < 2:
        return None

    prices.sort(key=lambda p: p["price"])
    best = prices[0]["price"]
    worst = prices[-1]["price"]
    spread = (worst - best) / worst * 100 if worst else 0.0

    return CrossRetailerComparison(
        product_id=product_id,
        product_name=product.name,
        volume_ml=product.volume_ml,
        prices=prices,
        best_retailer=prices[0]["retailer"],
        best_price=best,
        worst_price=worst,
        spread_pct=round(spread, 1),
    )
