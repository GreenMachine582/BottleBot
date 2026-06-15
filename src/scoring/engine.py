from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..calendar import SaleCalendar
from ..db.models import PriceHistory, RetailerProduct
from .criteria import Criteria

# Rough average CPL ($/L) per category, used to normalise the CPL score.
# Hardcoded benchmarks — tune after a few weeks of real data.
CATEGORY_AVG_CPL = {
    "whisky": 80,
    "wine_red": 30,
    "wine_white": 25,
    "gin": 70,
    "beer": 10,
    "rum": 65,
    "vodka": 55,
}


@dataclass
class DealScore:
    retailer_product_id: int
    product_name: str
    retailer: str
    url: str
    current_price: float
    avg_90d_price: float
    real_discount_pct: float  # vs 90-day average
    retailer_discount_pct: float  # vs retailer "was" price (for comparison)
    cpl_aud: float | None
    category: str | None
    volume_ml: int | None
    promo_label: str | None
    score: float  # 0-100
    score_breakdown: dict
    is_watchlist: bool
    is_new_low: bool
    bulk_saving_12: float  # Extra $ saved buying 12 vs 1


class ScoringEngine:
    def __init__(self, session: Session, criteria: Criteria):
        self.session = session
        self.criteria = criteria

    def get_90d_average(self, retailer_product_id: int) -> float | None:
        cutoff = datetime.utcnow() - timedelta(days=90)
        result = (
            self.session.query(func.avg(PriceHistory.price_aud))
            .filter(
                PriceHistory.retailer_product_id == retailer_product_id,
                PriceHistory.scraped_at >= cutoff,
            )
            .scalar()
        )
        return float(result) if result is not None else None

    def get_all_time_low(self, retailer_product_id: int) -> float | None:
        result = (
            self.session.query(func.min(PriceHistory.price_aud))
            .filter_by(retailer_product_id=retailer_product_id)
            .scalar()
        )
        return float(result) if result is not None else None

    def _is_watchlist(self, product_name: str, category: str | None) -> bool:
        c = self.criteria.watchlist
        if any(w.lower() in product_name.lower() for w in c.products):
            return True
        if category and category in c.categories:
            return True
        return False

    def _is_blocked(self, brand: str | None) -> bool:
        if not brand:
            return False
        b = self.criteria.brands
        if b.allowlist and not any(a.lower() in brand.lower() for a in b.allowlist):
            return True
        if any(bl.lower() in brand.lower() for bl in b.blocklist):
            return True
        return False

    def _in_sale_window(self) -> bool:
        return SaleCalendar().is_sale_window()

    def score_deal(self, rp: RetailerProduct, latest: PriceHistory) -> DealScore | None:
        product = rp.product
        avg = self.get_90d_average(rp.id)

        # Need at least a few days of history to score meaningfully
        if avg is None or avg == 0:
            return None

        real_discount_pct = (avg - latest.price_aud) / avg * 100
        if real_discount_pct < self.criteria.thresholds.min_discount_pct:
            return None

        saving_per_unit = avg - latest.price_aud
        if saving_per_unit < self.criteria.thresholds.min_saving_aud:
            return None

        if self._is_blocked(product.brand):
            return None

        # CPL calc
        cpl = None
        if product.volume_ml:
            cpl = latest.price_aud / (product.volume_ml / 1000)
            max_cpl = self.criteria.thresholds.max_cpl_aud.get(
                product.category or "",
                self.criteria.thresholds.max_cpl_aud.get("default", 9999),
            )
            if cpl > max_cpl:
                return None

        # Score components (each 0.0-1.0)
        discount_score = min(real_discount_pct / 60, 1.0)  # 60% = perfect score

        cpl_score = 0.5  # neutral if no volume/category data
        if cpl and product.category:
            cat_avg_cpl = CATEGORY_AVG_CPL.get(product.category)
            if cat_avg_cpl:
                cpl_score = min(max(1 - (cpl / cat_avg_cpl), 0), 1.0)

        bulk_saving = saving_per_unit * 12
        bulk_score = min(bulk_saving / 200, 1.0)  # $200 saved on 12 = perfect

        cat_mult = self.criteria.categories.get(product.category or "", 1.0)
        cat_score = min(max((cat_mult - 0.5) / 1.0, 0), 1.0)  # normalise 0.5-1.5 -> 0-1

        w = self.criteria.scoring.weights
        base = (
            discount_score * w.real_discount_pct
            + cpl_score * w.cpl_rating
            + bulk_score * w.bulk_value
            + cat_score * w.category_pref
        ) * 100

        # Modifiers
        mods = self.criteria.scoring.modifiers
        is_watchlist = self._is_watchlist(product.name, product.category)
        all_time_low = self.get_all_time_low(rp.id)
        is_new_low = all_time_low is not None and latest.price_aud <= all_time_low
        in_sale = self._in_sale_window()

        modifier_total = (
            (mods.watchlist_bonus if is_watchlist else 0)
            + (mods.new_low_bonus if is_new_low else 0)
            + (mods.eofy_window_bonus if in_sale else 0)
        )

        final_score = min(100, base + modifier_total)

        retailer_disc = 0.0
        if latest.was_price_aud:
            retailer_disc = (latest.was_price_aud - latest.price_aud) / latest.was_price_aud * 100

        return DealScore(
            retailer_product_id=rp.id,
            product_name=product.name,
            retailer=rp.retailer,
            url=rp.url,
            current_price=latest.price_aud,
            avg_90d_price=avg,
            real_discount_pct=real_discount_pct,
            retailer_discount_pct=retailer_disc,
            cpl_aud=cpl,
            category=product.category,
            volume_ml=product.volume_ml,
            promo_label=latest.promo_label,
            score=round(final_score, 1),
            score_breakdown={
                "discount": round(discount_score * w.real_discount_pct * 100, 1),
                "cpl": round(cpl_score * w.cpl_rating * 100, 1),
                "bulk": round(bulk_score * w.bulk_value * 100, 1),
                "category": round(cat_score * w.category_pref * 100, 1),
                "modifiers": round(modifier_total, 1),
            },
            is_watchlist=is_watchlist,
            is_new_low=is_new_low,
            bulk_saving_12=round(bulk_saving, 2),
        )

    def score_all_current_deals(self) -> list[DealScore]:
        """Score all products currently marked on_sale, return sorted by score desc."""
        results = []

        on_sale = (
            self.session.query(RetailerProduct)
            .join(PriceHistory)
            .filter(PriceHistory.on_sale.is_(True))
            .distinct()
            .all()
        )

        for rp in on_sale:
            latest = (
                self.session.query(PriceHistory)
                .filter_by(retailer_product_id=rp.id)
                .order_by(PriceHistory.scraped_at.desc())
                .first()
            )
            if latest:
                score = self.score_deal(rp, latest)
                if score and score.score >= self.criteria.alerts.min_deal_score:
                    results.append(score)

        return sorted(results, key=lambda d: d.score, reverse=True)
