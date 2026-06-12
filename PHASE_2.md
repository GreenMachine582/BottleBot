# Phase 2 — Intelligence: Score & Alert

> **Goal:** Turn raw price data into ranked deal scores and fire alerts through ntfy and Discord when something clears your configured threshold. Daily digest mode for less urgent deals.

**Estimated effort:** 1–2 weekends  
**Depends on:** Phase 1 (needs price history to calculate real discounts)  
**Unlocks:** Phase 3 (more sources feed the same scoring pipeline)

---

## Deliverables

- [ ] `criteria.yaml` schema + Pydantic config loader
- [ ] Deal scoring engine (weighted formula, 0–100 score)
- [ ] 90-day rolling average calculator (real discount vs retailer "was" price)
- [ ] ntfy alert module
- [ ] Discord webhook alert module
- [ ] Daily digest builder (sorted by score, top N deals)
- [ ] Immediate alert mode for high-score deals
- [ ] EOFY / sale calendar awareness (threshold modifier)
- [ ] Dry-run CLI for testing scoring without sending alerts

---

## 1. Criteria config schema

```yaml
# config/criteria.yaml

alerts:
  min_deal_score: 65            # 0-100. Deals below this are ignored entirely.
  immediate_threshold: 85       # Score at or above this fires immediately (bypass digest)
  digest_time: "08:00"          # Daily digest send time (AEST)
  digest_max_deals: 10          # Max deals to include in daily digest
  channels:
    ntfy:
      enabled: true
      url: "https://ntfy.yourdomain.com"
      topic: "bottlebot-deals"
      priority: 3               # ntfy priority 1-5
    discord:
      enabled: true
      webhook_url: "https://discord.com/api/webhooks/YOUR_WEBHOOK"
    email:
      enabled: false
      smtp_host: "smtp.gmail.com"
      smtp_port: 587
      from_addr: "you@gmail.com"
      to_addr: "you@gmail.com"

scoring:
  weights:
    real_discount_pct: 0.35     # Discount vs 90-day average (not retailer "was")
    cpl_rating:        0.30     # Cost per litre vs category average
    bulk_value:        0.20     # Extra savings when buying 12+
    category_pref:     0.15     # Personal category preference multiplier

  # Bonus/penalty modifiers (additive to base score, capped at 100)
  modifiers:
    watchlist_bonus: 20         # Flat bonus for watchlist items
    eofy_window_bonus: 10       # Bonus during EOFY/Boxing Day windows
    new_low_bonus: 15           # Bonus if this is the all-time lowest scraped price

categories:
  whisky:   1.4
  wine_red: 1.2
  wine_white: 1.0
  gin:      1.1
  rum:      1.0
  vodka:    0.9
  beer:     0.8
  cider:    0.7
  rtd:      0.5
  wine_sparkling: 1.1

thresholds:
  min_discount_pct: 20          # Ignore deals with less than 20% real discount
  min_saving_aud: 10            # Ignore deals saving less than $10 per bottle
  max_cpl_aud:                  # Skip if $/L still exceeds this after discount
    whisky:     60
    wine_red:   25
    wine_white: 20
    beer:       8
    gin:        55
    default:    30

watchlist:
  products:
    - "Johnnie Walker Black Label"
    - "Penfolds Bin 389"
    - "Archie Rose White Rye"
  categories: []                # e.g. ["whisky"] to watch all whisky deals

brands:
  blocklist:
    - "Black Douglas"
    - "Woodstock"
  allowlist: []                 # Empty = all brands (except blocklist)
```

---

## 2. Config loader

```python
# bottlebot/scoring/criteria.py
from pathlib import Path
from pydantic import BaseModel, Field
import yaml

class ChannelConfig(BaseModel):
    enabled: bool = False

class NtfyConfig(ChannelConfig):
    url: str = ""
    topic: str = "bottlebot-deals"
    priority: int = 3

class DiscordConfig(ChannelConfig):
    webhook_url: str = ""

class EmailConfig(ChannelConfig):
    smtp_host: str = ""
    smtp_port: int = 587
    from_addr: str = ""
    to_addr: str = ""

class AlertsConfig(BaseModel):
    min_deal_score: float = 65
    immediate_threshold: float = 85
    digest_time: str = "08:00"
    digest_max_deals: int = 10
    channels: dict = Field(default_factory=dict)

class ScoringWeights(BaseModel):
    real_discount_pct: float = 0.35
    cpl_rating: float = 0.30
    bulk_value: float = 0.20
    category_pref: float = 0.15

class ScoringModifiers(BaseModel):
    watchlist_bonus: float = 20
    eofy_window_bonus: float = 10
    new_low_bonus: float = 15

class ScoringConfig(BaseModel):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    modifiers: ScoringModifiers = Field(default_factory=ScoringModifiers)

class Thresholds(BaseModel):
    min_discount_pct: float = 20
    min_saving_aud: float = 10
    max_cpl_aud: dict[str, float] = Field(default_factory=lambda: {"default": 30})

class WatchlistConfig(BaseModel):
    products: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)

class BrandsConfig(BaseModel):
    blocklist: list[str] = Field(default_factory=list)
    allowlist: list[str] = Field(default_factory=list)

class Criteria(BaseModel):
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    categories: dict[str, float] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    brands: BrandsConfig = Field(default_factory=BrandsConfig)

def load_criteria(path: str | Path = "config/criteria.yaml") -> Criteria:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Criteria.model_validate(data)
```

---

## 3. Deal scoring engine

### Scoring formula

Each deal gets a **base score** (0–100) from four weighted components, then **modifiers** are added on top (capped at 100).

```
base_score = (
    real_discount_score  * weight.real_discount_pct  +   # How deep is the real discount?
    cpl_score            * weight.cpl_rating          +   # Is $/L good for this category?
    bulk_value_score     * weight.bulk_value           +   # Does buying 12 save more?
    category_pref_score  * weight.category_pref            # Do you care about this category?
) * 100

final_score = min(100, base_score + modifiers)
```

```python
# bottlebot/scoring/engine.py
from dataclasses import dataclass
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db.models import PriceHistory, RetailerProduct, Product
from .criteria import Criteria

@dataclass
class DealScore:
    retailer_product_id: int
    product_name: str
    retailer: str
    url: str
    current_price: float
    avg_90d_price: float
    real_discount_pct: float        # vs 90-day average
    retailer_discount_pct: float    # vs retailer "was" price (for comparison)
    cpl_aud: float | None
    category: str | None
    volume_ml: int | None
    promo_label: str | None
    score: float                    # 0-100
    score_breakdown: dict
    is_watchlist: bool
    is_new_low: bool
    bulk_saving_12: float           # Extra $ saved buying 12 vs 1

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
        return float(result) if result else None

    def get_all_time_low(self, retailer_product_id: int) -> float | None:
        result = (
            self.session.query(func.min(PriceHistory.price_aud))
            .filter_by(retailer_product_id=retailer_product_id)
            .scalar()
        )
        return float(result) if result else None

    def _category_avg_cpl(self, category: str) -> float | None:
        """Rough average CPL for a category to normalise against."""
        # Hardcoded benchmarks ($/L). Tune after a few weeks of data.
        benchmarks = {
            "whisky": 80, "wine_red": 30, "wine_white": 25,
            "gin": 70, "beer": 10, "rum": 65, "vodka": 55,
        }
        return benchmarks.get(category)

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
        """True if today is within a known AU sale window."""
        from ..calendar import SaleCalendar
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
                self.criteria.thresholds.max_cpl_aud.get("default", 9999)
            )
            if cpl > max_cpl:
                return None

        # Score components (each 0.0–1.0)
        discount_score = min(real_discount_pct / 60, 1.0)   # 60% = perfect score

        cpl_score = 0.5  # neutral if no volume data
        if cpl and product.category:
            cat_avg_cpl = self._category_avg_cpl(product.category)
            if cat_avg_cpl:
                cpl_score = min(max(1 - (cpl / cat_avg_cpl), 0), 1.0)

        bulk_saving = saving_per_unit * 12
        bulk_score = min(bulk_saving / 200, 1.0)   # $200 saved on 12 = perfect

        cat_mult = self.criteria.categories.get(product.category or "", 1.0)
        cat_score = min((cat_mult - 0.5) / 1.0, 1.0)   # normalise 0.5–1.5 → 0–1

        w = self.criteria.scoring.weights
        base = (
            discount_score * w.real_discount_pct +
            cpl_score      * w.cpl_rating +
            bulk_score     * w.bulk_value +
            cat_score      * w.category_pref
        ) * 100

        # Modifiers
        mods = self.criteria.scoring.modifiers
        is_watchlist = self._is_watchlist(product.name, product.category)
        all_time_low = self.get_all_time_low(rp.id)
        is_new_low = all_time_low is not None and latest.price_aud <= all_time_low
        in_sale = self._in_sale_window()

        modifier_total = (
            (mods.watchlist_bonus  if is_watchlist else 0) +
            (mods.new_low_bonus    if is_new_low   else 0) +
            (mods.eofy_window_bonus if in_sale     else 0)
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
                "cpl":      round(cpl_score      * w.cpl_rating * 100, 1),
                "bulk":     round(bulk_score      * w.bulk_value * 100, 1),
                "category": round(cat_score       * w.category_pref * 100, 1),
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
            .filter(PriceHistory.on_sale == True)
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
```

---

## 4. Sale calendar

```python
# bottlebot/calendar.py
from datetime import date

SALE_WINDOWS = [
    # (label, month, day_start, day_end)
    ("EOFY",        6,  15, 30),
    ("Boxing Day",  12, 26, 31),
    ("New Year",    1,  1,  7),
    ("Easter",      4,  1,  10),   # Approximate; Easter is moveable
    ("Click Frenzy",11, 10, 14),
]

class SaleCalendar:
    def is_sale_window(self, d: date | None = None) -> bool:
        d = d or date.today()
        for label, month, start, end in SALE_WINDOWS:
            if d.month == month and start <= d.day <= end:
                return True
        return False

    def current_window(self, d: date | None = None) -> str | None:
        d = d or date.today()
        for label, month, start, end in SALE_WINDOWS:
            if d.month == month and start <= d.day <= end:
                return label
        return None
```

---

## 5. Alert modules

### ntfy

```python
# bottlebot/alerts/ntfy.py
import httpx
from ..scoring.engine import DealScore

def send_ntfy_alert(deal: DealScore, ntfy_url: str, topic: str, priority: int = 3):
    title = f"{'🔥 ' if deal.score >= 85 else '🍺 '}Deal: {deal.product_name}"
    body_lines = [
        f"${deal.current_price:.2f} — {deal.real_discount_pct:.0f}% off 90d avg (was ${deal.avg_90d_price:.2f})",
        f"Score: {deal.score}/100",
    ]
    if deal.cpl_aud:
        body_lines.append(f"${deal.cpl_aud:.2f}/L")
    if deal.is_watchlist:
        body_lines.append("⭐ Watchlist item")
    if deal.is_new_low:
        body_lines.append("📉 All-time low price")
    if deal.bulk_saving_12 > 0:
        body_lines.append(f"Buy 12 → save ${deal.bulk_saving_12:.0f}")
    body_lines.append(deal.url)

    httpx.post(
        f"{ntfy_url}/{topic}",
        data="\n".join(body_lines),
        headers={
            "Title": title,
            "Priority": str(priority),
            "Tags": "beers" if deal.score < 85 else "fire,beers",
            "Click": deal.url,
        },
        timeout=10,
    )
```

### Discord

```python
# bottlebot/alerts/discord.py
import httpx
from ..scoring.engine import DealScore

def send_discord_alert(deal: DealScore, webhook_url: str):
    color = 0xFF6B35 if deal.score >= 85 else 0x5BCAA5   # orange = hot, teal = good
    embed = {
        "title": deal.product_name,
        "url": deal.url,
        "color": color,
        "fields": [
            {"name": "Price",     "value": f"**${deal.current_price:.2f}**", "inline": True},
            {"name": "Real disc", "value": f"{deal.real_discount_pct:.0f}% off 90d avg", "inline": True},
            {"name": "Score",     "value": f"{deal.score}/100", "inline": True},
        ],
        "footer": {"text": f"{deal.retailer} · {deal.promo_label or 'On sale'}"},
    }
    if deal.cpl_aud:
        embed["fields"].append({"name": "$/L", "value": f"${deal.cpl_aud:.2f}", "inline": True})
    if deal.is_new_low:
        embed["fields"].append({"name": "📉", "value": "All-time low", "inline": True})
    if deal.bulk_saving_12:
        embed["fields"].append({"name": "Buy 12", "value": f"Save ${deal.bulk_saving_12:.0f}", "inline": True})

    httpx.post(webhook_url, json={"embeds": [embed]}, timeout=10)
```

---

## 6. Daily digest

```python
# bottlebot/alerts/digest.py
from .ntfy import send_ntfy_alert
from .discord import send_discord_alert
from ..scoring.engine import DealScore
from ..scoring.criteria import Criteria

def send_digest(deals: list[DealScore], criteria: Criteria):
    """Send top N deals as a daily digest. Immediate alerts are sent separately."""
    cfg = criteria.alerts
    top = deals[:cfg.digest_max_deals]

    ntfy_cfg = cfg.channels.get("ntfy", {})
    discord_cfg = cfg.channels.get("discord", {})

    # ntfy: one message per deal in digest
    if ntfy_cfg.get("enabled"):
        for deal in top:
            send_ntfy_alert(
                deal,
                ntfy_url=ntfy_cfg["url"],
                topic=ntfy_cfg["topic"] + "-digest",
                priority=2,   # Lower priority for digest
            )

    # Discord: single embed list
    if discord_cfg.get("enabled") and top:
        lines = [f"**BottleBot Daily Digest — Top {len(top)} deals**\n"]
        for i, d in enumerate(top, 1):
            lines.append(
                f"{i}. [{d.product_name}]({d.url}) — "
                f"${d.current_price:.2f} · {d.real_discount_pct:.0f}% off · Score {d.score}"
            )
        import httpx
        httpx.post(discord_cfg["webhook_url"], json={"content": "\n".join(lines)}, timeout=10)
```

---

## 7. Wiring it together

```python
# bottlebot/run_scoring.py
"""Run after each scrape. Called by scheduler or CLI."""
import logging
from sqlalchemy.orm import Session
from .db.models import Base
from sqlalchemy import create_engine
from .scoring.engine import ScoringEngine
from .scoring.criteria import load_criteria
from .alerts.ntfy import send_ntfy_alert
from .alerts.discord import send_discord_alert
from .alerts.digest import send_digest

log = logging.getLogger(__name__)

def run_scoring(db_path: str = "bottlebot.db", criteria_path: str = "config/criteria.yaml"):
    engine = create_engine(f"sqlite:///{db_path}")
    criteria = load_criteria(criteria_path)

    with Session(engine) as session:
        scorer = ScoringEngine(session, criteria)
        deals = scorer.score_all_current_deals()

    log.info(f"Scored {len(deals)} deals above threshold {criteria.alerts.min_deal_score}")

    ntfy_cfg = criteria.alerts.channels.get("ntfy", {})
    discord_cfg = criteria.alerts.channels.get("discord", {})

    immediate = [d for d in deals if d.score >= criteria.alerts.immediate_threshold]
    digest = [d for d in deals if d.score < criteria.alerts.immediate_threshold]

    # Fire immediately for hot deals
    for deal in immediate:
        log.info(f"Immediate alert: {deal.product_name} ({deal.score})")
        if ntfy_cfg.get("enabled"):
            send_ntfy_alert(deal, ntfy_cfg["url"], ntfy_cfg["topic"], priority=5)
        if discord_cfg.get("enabled"):
            send_discord_alert(deal, discord_cfg["webhook_url"])

    # Digest goes out at scheduled time (separate cron job)
    # This function just returns the digest list for the scheduler to hold
    return {"immediate": immediate, "digest": digest}
```

---

## 8. Dry-run CLI

```bash
# Test scoring without sending alerts
python -m bottlebot.run_scoring --dry-run --top 20

# Output:
# Rank  Score  Discount  $/L    Product
#  1    92.4   38% off   $42/L  Johnnie Walker Black 700mL — Dan Murphy's $38
#  2    81.0   31% off   $21/L  Penfolds Bin 389 2021 — BWS $46
#  ...
```

---

## Phase 2 acceptance criteria

- [ ] Scoring engine returns ranked deals from the DB
- [ ] Deals below `min_discount_pct` or `min_saving_aud` are filtered
- [ ] Blocklisted brands are excluded
- [ ] Watchlist items receive bonus score and appear at top
- [ ] Immediate alerts fire for scores ≥ `immediate_threshold`
- [ ] ntfy alert received on phone for a test deal
- [ ] Discord embed received with correct fields
- [ ] Daily digest scheduled correctly and sends at configured time
- [ ] Dry-run prints ranked table without sending any alert
- [ ] EOFY window modifier applies correctly in June

---

## Known gotchas

- **90-day average is meaningless until Phase 1 has been running for a week+.** The first days of data will show everything as a "deal" because there's nothing to compare against. Add a guard: require at least 7 data points before scoring a product.
- **Retailer "was" prices are unreliable.** Dan Murphy's sometimes inflates the "was" price right before a sale. Always use the 90d average as the source of truth; show the retailer discount alongside for reference only.
- **ntfy rate limits:** On a self-hosted instance you control limits, but don't fire more than one message per second or the Pi's ntfy container may queue-stall. Add a 0.5s sleep between alerts in the immediate fire loop.

---

*Previous: [Phase 1 — Foundation](./PHASE_1.md) · Next: [Phase 3 — Breadth](./PHASE_3.md)*
