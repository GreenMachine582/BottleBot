from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from ..scrapers.base import ScrapedProduct
from .matching import find_matching_product
from .models import PriceHistory, Product, RetailerProduct


def upsert_product(
    session: Session,
    scraped: ScrapedProduct,
    enrich_fn: Callable[[ScrapedProduct], ScrapedProduct] | None = None,
) -> tuple[RetailerProduct, bool]:
    """
    Find or create RetailerProduct. Returns (retailer_product, price_changed).
    Only inserts a new PriceHistory row if the price has actually changed.

    `enrich_fn` (typically a scraper's `.enrich()`) is called only when a
    brand-new Product row is about to be created — a one-time cost per
    product rather than a per-scrape cost for products we already know.
    """
    rp = session.query(RetailerProduct).filter_by(
        retailer=scraped.retailer,
        url=scraped.url
    ).first()

    if not rp:
        product = find_matching_product(
            session, scraped.name, scraped.brand, scraped.volume_ml
        )
        if not product:
            if enrich_fn:
                scraped = enrich_fn(scraped)
            product = Product(
                name=scraped.name,
                brand=scraped.brand,
                category=scraped.category,
                subcategory=scraped.subcategory,
                volume_ml=scraped.volume_ml,
                abv=scraped.abv,
            )
            session.add(product)
            session.flush()

        rp = RetailerProduct(
            product_id=product.id,
            retailer=scraped.retailer,
            retailer_sku=scraped.retailer_sku,
            url=scraped.url,
            image_url=scraped.image_url,
        )
        session.add(rp)
        session.flush()

    # Check if price changed since last observation
    last = (
        session.query(PriceHistory)
        .filter_by(retailer_product_id=rp.id)
        .order_by(PriceHistory.scraped_at.desc())
        .first()
    )
    price_changed = last is None or last.price_aud != scraped.price_aud

    if price_changed:
        ph = PriceHistory(
            retailer_product_id=rp.id,
            price_aud=scraped.price_aud,
            was_price_aud=scraped.was_price_aud,
            in_stock=scraped.in_stock,
            on_sale=scraped.on_sale,
            promo_label=scraped.promo_label,
            scraped_at=datetime.utcnow(),
        )
        session.add(ph)

    return rp, price_changed
