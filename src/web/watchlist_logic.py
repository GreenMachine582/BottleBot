"""Pure helpers for mapping per-volume watchlist toggles onto the flat
substring-match string list that ScoringEngine._is_watchlist reads from
config/criteria.yaml. No DB writes happen here — callers own the session
and the YAML read/write.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..db.models import Product
from .utils import clean_product_name


@dataclass(frozen=True)
class ProductGroup:
    clean_name: str
    brand: str | None
    category: str | None
    volumes: list[Product]


def group_products(products: list[Product]) -> list[ProductGroup]:
    """Group flat Product rows into one ProductGroup per (clean_name, brand),
    preserving first-seen order. Volumes within a group are sorted ascending."""
    groups: dict[tuple[str, str | None], list[Product]] = {}
    order: list[tuple[str, str | None]] = []
    for p in products:
        key = (clean_product_name(p.name), p.brand)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)

    result = []
    for key in order:
        clean_name, brand = key
        volumes = sorted(groups[key], key=lambda p: p.volume_ml or 0)
        result.append(ProductGroup(
            clean_name=clean_name,
            brand=brand,
            category=volumes[0].category,
            volumes=volumes,
        ))
    return result


def find_siblings(session: Session, product: Product) -> list[Product]:
    """All Product rows sharing the same (clean_name, brand) as `product`,
    including itself."""
    clean = clean_product_name(product.name)
    candidates = session.query(Product).filter(Product.brand == product.brand).all()
    return [p for p in candidates if clean_product_name(p.name) == clean]


def is_volume_watched(product: Product, watch_products: list[str]) -> bool:
    """True if this exact volume is watched directly, or covered by a
    blanket (no-volume) watch on the product's clean name."""
    clean = clean_product_name(product.name)
    return product.name in watch_products or clean in watch_products


def toggle_volume_on(watch_products: list[str], product: Product) -> list[str]:
    """Returns a new list with this volume watched. No-op if already covered
    directly or via an existing blanket clean-name entry."""
    clean = clean_product_name(product.name)
    if clean in watch_products or product.name in watch_products:
        return watch_products
    return [*watch_products, product.name]


def toggle_volume_off(
    watch_products: list[str],
    product: Product,
    siblings: list[Product],
) -> list[str]:
    """Returns a new list with this volume unwatched. If only a blanket
    clean-name entry covered it, expands that into explicit full-name
    entries for every other sibling so they stay watched."""
    clean = clean_product_name(product.name)
    result = list(watch_products)

    if product.name in result:
        result.remove(product.name)
        return result

    if clean in result:
        result.remove(clean)
        for sib in siblings:
            if sib.id != product.id and sib.name not in result:
                result.append(sib.name)
        return result

    return result
