from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db.models import PriceHistory, Product, RetailerProduct


@dataclass
class CrossRetailerComparison:
    product_id: int
    product_name: str
    volume_ml: int | None
    prices: list[dict]  # enriched per-retailer dicts
    best_retailer: str
    best_price: float
    worst_price: float
    spread_pct: float


def _retailer_avg_90d(session: Session, rp_id: int) -> float | None:
    cutoff = datetime.utcnow() - timedelta(days=90)
    result = session.query(func.avg(PriceHistory.price_aud)).filter(
        PriceHistory.retailer_product_id == rp_id,
        PriceHistory.scraped_at >= cutoff,
    ).scalar()
    return float(result) if result is not None else None


def compare_product_across_retailers(
    session: Session, product_id: int, current_rp_id: int | None = None
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
                "rp_id": rp.id,
                "price": latest.price_aud,
                "url": rp.url,
                "on_sale": latest.on_sale,
                "promo_label": latest.promo_label,
                "retailer_sku": rp.retailer_sku,
                "avg_90d": _retailer_avg_90d(session, rp.id),
                "is_current": rp.id == current_rp_id,
                "delta": None,
            })

    if len(prices) < 2:
        return None

    prices.sort(key=lambda p: p["price"])
    best = prices[0]["price"]
    worst = prices[-1]["price"]
    spread = (worst - best) / worst * 100 if worst else 0.0

    # Compute delta vs the current retailer's price
    if current_rp_id is not None:
        current_entry = next((p for p in prices if p["rp_id"] == current_rp_id), None)
        if current_entry:
            current_price = current_entry["price"]
            for entry in prices:
                entry["delta"] = entry["price"] - current_price

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
