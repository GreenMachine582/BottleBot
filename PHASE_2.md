# Phase 2 — Intelligence: Score & Alert

> **Goal:** Turn raw price data into ranked deal scores and fire alerts via [apprise](https://github.com/caronc/apprise) — Discord is the primary channel, with ntfy, email, and 100+ other services available through the same config — when something clears your configured threshold. Daily digest mode for less urgent deals.

**Estimated effort:** 1–2 weekends  
**Depends on:** Phase 1 (needs price history to calculate real discounts)  
**Unlocks:** Phase 3 (more sources feed the same scoring pipeline)

---

## Deliverables

- [ ] `criteria.yaml` schema + Pydantic config loader
- [ ] `.env`-based secrets via pydantic-settings (Discord webhook URL, ntfy URL, etc.)
- [ ] Deal scoring engine (weighted formula, 0–100 score)
- [ ] 90-day rolling average calculator (real discount vs retailer "was" price)
- [ ] apprise-based notification module — Discord primary, ntfy/email/Slack/etc. as additional targets
- [ ] Alert messages link to both the retailer product page and the Phase 4 dashboard
- [ ] Daily digest builder (sorted by score, top N deals)
- [ ] Immediate alert mode for high-score deals
- [ ] EOFY / Boxing Day / Easter sale calendar awareness (threshold modifier, Easter date computed via `dateutil`)
- [ ] Dry-run CLI (`src.cli score`) using typer + rich

---

## 1. Criteria config schema

```yaml
# config/criteria.yaml

alerts:
  min_deal_score: 65            # 0-100. Deals below this are ignored entirely.
  immediate_threshold: 85       # Score at or above this fires immediately (bypass digest)
  digest_time: "08:00"          # Daily digest send time (AEST)
  digest_max_deals: 10          # Max deals to include in daily digest

web:
  base_url: "http://localhost:8080"   # Phase 4 dashboard URL — used to build "View on BottleBot" links in alerts

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

### Notification secrets (`.env`)

Webhook URLs and tokens are secrets and don't belong in `criteria.yaml`. BottleBot loads them from
a `.env` file (gitignored) via `pydantic-settings`.

```python
# src/config/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Secrets loaded from .env — never committed to git."""
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BOTTLEBOT_", extra="ignore")

    # Discord webhook, in apprise's native format: discord://<webhook_id>/<webhook_token>
    # (take the id/token pair from the webhook URL Discord gives you)
    discord_webhook_url: str = ""

    # Optional extra apprise targets, e.g. ntfy://ntfy.sh/bottlebot-deals
    ntfy_url: str = ""

    # BWS internal API key (Phase 3) — extracted from their frontend JS bundle
    bws_subscription_key: str = ""
```

```bash
# .env.example — copy to .env, fill in, and keep .env out of git
BOTTLEBOT_DISCORD_WEBHOOK_URL=discord://123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz
BOTTLEBOT_NTFY_URL=ntfy://ntfy.sh/bottlebot-deals
BOTTLEBOT_BWS_SUBSCRIPTION_KEY=
```

---

## 2. Config loader

```python
# src/scoring/criteria.py
from pathlib import Path
from pydantic import BaseModel, Field
import yaml

class AlertsConfig(BaseModel):
    min_deal_score: float = 65
    immediate_threshold: float = 85
    digest_time: str = "08:00"
    digest_max_deals: int = 10

class WebConfig(BaseModel):
    base_url: str = "http://localhost:8080"

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
    web: WebConfig = Field(default_factory=WebConfig)
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
# src/scoring/engine.py
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
# src/calendar.py
from datetime import date, timedelta
from dateutil.easter import easter

# Fixed-date sale windows: (label, month, day_start, day_end)
FIXED_SALE_WINDOWS = [
    ("EOFY",         6,  15, 30),
    ("Boxing Day",   12, 26, 31),
    ("New Year",     1,   1,  7),
    ("Click Frenzy", 11,  10, 14),
]

# Easter is a moveable feast — compute it per-year with dateutil rather than
# hardcoding a date range. Window covers the lead-up through the long weekend.
EASTER_LEAD_DAYS = 4     # Sale window starts this many days before Good Friday
EASTER_TRAIL_DAYS = 1    # ...and ends this many days after Easter Monday

class SaleCalendar:
    def _easter_window(self, year: int) -> tuple[date, date]:
        sunday = easter(year)
        good_friday = sunday - timedelta(days=2)
        easter_monday = sunday + timedelta(days=1)
        return good_friday - timedelta(days=EASTER_LEAD_DAYS), easter_monday + timedelta(days=EASTER_TRAIL_DAYS)

    def is_sale_window(self, d: date | None = None) -> bool:
        return self.current_window(d) is not None

    def current_window(self, d: date | None = None) -> str | None:
        d = d or date.today()
        for label, month, start, end in FIXED_SALE_WINDOWS:
            if d.month == month and start <= d.day <= end:
                return label

        start, end = self._easter_window(d.year)
        if start <= d <= end:
            return "Easter"
        return None
```

---

## 5. Alert module

A single `notify.py` module wraps [apprise](https://github.com/caronc/apprise), which gives one
interface to Discord, ntfy, email, Slack, Telegram, and 100+ other services. Discord is the
primary target. Every alert links to both the retailer's product page (to buy) and the BottleBot
dashboard from Phase 4 (to see the price history chart and cross-retailer comparison).

```python
# src/alerts/notify.py
import apprise
from ..config.settings import Settings
from ..scoring.engine import DealScore

def build_message(deal: DealScore, base_url: str) -> tuple[str, str]:
    """Build a (title, markdown body) pair for a single deal."""
    title = f"{'🔥' if deal.score >= 85 else '🍺'} {deal.product_name}"

    lines = [
        f"**${deal.current_price:.2f}** — {deal.real_discount_pct:.0f}% off 90-day avg "
        f"(was ${deal.avg_90d_price:.2f})",
        f"Score: **{deal.score}/100**",
    ]
    if deal.cpl_aud:
        lines.append(f"${deal.cpl_aud:.2f}/L")
    if deal.is_watchlist:
        lines.append("⭐ Watchlist item")
    if deal.is_new_low:
        lines.append("📉 All-time low price")
    if deal.bulk_saving_12 > 0:
        lines.append(f"Buy 12 → save ${deal.bulk_saving_12:.0f}")

    dashboard_url = f"{base_url}/deals/{deal.retailer_product_id}"
    lines.append(f"\n[Buy at {deal.retailer.title()}]({deal.url}) · [View on BottleBot]({dashboard_url})")

    return title, "\n".join(lines)

def build_apprise(settings: Settings) -> apprise.Apprise:
    """Assemble notification targets from .env-sourced settings."""
    apobj = apprise.Apprise()
    if settings.discord_webhook_url:
        apobj.add(settings.discord_webhook_url, tag=["immediate", "digest"])
    if settings.ntfy_url:
        apobj.add(settings.ntfy_url, tag=["digest"])
    return apobj

def send_alert(apobj: apprise.Apprise, deal: DealScore, base_url: str, tag: str = "immediate"):
    title, body = build_message(deal, base_url)
    apobj.notify(title=title, body=body, body_format=apprise.NotifyFormat.MARKDOWN, tag=tag)
```

> **Adding more channels:** any [apprise URL](https://github.com/caronc/apprise/wiki) works — Slack
> (`slack://...`), Telegram (`tgram://...`), email (`mailtos://...`), Pushover, and dozens more.
> Add a field to `Settings`, then `apobj.add(...)` it in `build_apprise()` with the right tag(s).

---

## 6. Daily digest

```python
# src/alerts/digest.py
import apprise
from ..scoring.engine import DealScore
from ..scoring.criteria import Criteria

def send_digest(apobj: apprise.Apprise, deals: list[DealScore], criteria: Criteria):
    """Send the top N deals as a single daily digest notification."""
    top = deals[:criteria.alerts.digest_max_deals]
    if not top:
        return

    base_url = criteria.web.base_url
    lines = [f"**BottleBot Daily Digest — Top {len(top)} deals**\n"]
    for i, d in enumerate(top, 1):
        dashboard_url = f"{base_url}/deals/{d.retailer_product_id}"
        lines.append(
            f"{i}. **{d.product_name}** — ${d.current_price:.2f} · "
            f"{d.real_discount_pct:.0f}% off · Score {d.score}\n"
            f"   [Buy at {d.retailer.title()}]({d.url}) · [View on BottleBot]({dashboard_url})"
        )

    apobj.notify(
        title="BottleBot Daily Digest",
        body="\n".join(lines),
        body_format=apprise.NotifyFormat.MARKDOWN,
        tag="digest",
    )
```

---

## 7. Wiring it together

```python
# src/run_scoring.py
"""Run after each scrape. Called by scheduler or CLI."""
import logging
import time
from sqlalchemy.orm import Session
from .db.engine import engine
from .scoring.engine import ScoringEngine
from .scoring.criteria import load_criteria
from .config.settings import Settings
from .alerts.notify import build_apprise, send_alert

log = logging.getLogger(__name__)

def run_scoring(criteria_path: str = "config/criteria.yaml"):
    criteria = load_criteria(criteria_path)
    apobj = build_apprise(Settings())

    with Session(engine) as session:
        scorer = ScoringEngine(session, criteria)
        deals = scorer.score_all_current_deals()

    log.info(f"Scored {len(deals)} deals above threshold {criteria.alerts.min_deal_score}")

    immediate = [d for d in deals if d.score >= criteria.alerts.immediate_threshold]
    digest = [d for d in deals if d.score < criteria.alerts.immediate_threshold]

    # Fire immediately for hot deals
    for deal in immediate:
        log.info(f"Immediate alert: {deal.product_name} ({deal.score})")
        send_alert(apobj, deal, criteria.web.base_url, tag="immediate")
        time.sleep(0.5)   # be polite to self-hosted ntfy/Discord rate limits

    # Digest goes out at criteria.alerts.digest_time (separate scheduled job calls send_digest)
    return {"immediate": immediate, "digest": digest}
```

### Scheduling scoring & digests

Two more jobs join the scrape jobs in `src/scheduler.py`: one that scores and fires immediate
alerts shortly after each scrape, and a daily digest job at `criteria.alerts.digest_time`.

```python
# src/scheduler.py (Phase 2 addition)
from sqlalchemy.orm import Session
from .db.engine import engine
from .run_scoring import run_scoring
from .scoring.engine import ScoringEngine
from .scoring.criteria import load_criteria
from .alerts.notify import build_apprise
from .alerts.digest import send_digest
from .config.settings import Settings

def run_digest():
    criteria = load_criteria()
    with Session(engine) as session:
        deals = ScoringEngine(session, criteria).score_all_current_deals()
    send_digest(build_apprise(Settings()), deals, criteria)

# Score + fire immediate alerts ~5 minutes after the Dan Murphy's scrape
scheduler.add_job(run_scoring, "interval", hours=6, minutes=5)

# Daily digest at criteria.alerts.digest_time (e.g. "08:00" AEST)
_digest_hour, _digest_minute = (int(p) for p in load_criteria().alerts.digest_time.split(":"))
scheduler.add_job(run_digest, "cron", hour=_digest_hour, minute=_digest_minute)
```

---

## 8. Dry-run CLI

A small [typer](https://typer.tiangolo.com/) app with [rich](https://rich.readthedocs.io/) table
output — score the current deal set and print a ranked table without sending any notifications.
This `score` command lives in the same `src/cli.py` as Phase 1's `scrape` command, sharing the
one `app = typer.Typer(...)` instance.

```python
# src/cli.py (Phase 2 addition)
import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session
from .db.engine import engine
from .scoring.engine import ScoringEngine
from .scoring.criteria import load_criteria

console = Console()

@app.command()
def score(
    criteria_path: str = typer.Option("config/criteria.yaml", help="Path to criteria config"),
    top: int = typer.Option(20, help="Number of deals to show"),
):
    """Score current deals and print a ranked table — no alerts are sent."""
    criteria = load_criteria(criteria_path)

    with Session(engine) as session:
        scorer = ScoringEngine(session, criteria)
        deals = scorer.score_all_current_deals()

    table = Table(title=f"Top {min(top, len(deals))} deals")
    table.add_column("Rank", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Discount", justify="right")
    table.add_column("$/L", justify="right")
    table.add_column("Product")
    table.add_column("Retailer")
    table.add_column("Price", justify="right")

    for i, d in enumerate(deals[:top], 1):
        table.add_row(
            str(i),
            f"{d.score:.1f}",
            f"{d.real_discount_pct:.0f}%",
            f"${d.cpl_aud:.2f}" if d.cpl_aud else "—",
            d.product_name,
            d.retailer.title(),
            f"${d.current_price:.2f}",
        )

    console.print(table)
```

```bash
# Score the current deal set without sending any alerts
python -m src.cli score --top 20

#         Top 20 deals
# ┏━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
# ┃ Rank ┃ Score ┃ Discount ┃   $/L ┃ Product                ┃ Retailer   ┃ Price ┃
# ┡━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
# │    1 │  92.4 │      38% │ $42.0 │ Johnnie Walker Black   │ Danmurphys │ $38.00│
# │    2 │  81.0 │      31% │ $21.0 │ Penfolds Bin 389 2021  │ Bws        │ $46.00│
# └──────┴───────┴──────────┴───────┴────────────────────────┴────────────┴───────┘
```

---

## Phase 2 acceptance criteria

- [ ] Scoring engine returns ranked deals from the DB
- [ ] Deals below `min_discount_pct` or `min_saving_aud` are filtered
- [ ] Blocklisted brands are excluded
- [ ] Watchlist items receive bonus score and appear at top
- [ ] Immediate alerts fire for scores ≥ `immediate_threshold`
- [ ] Discord message received via apprise with correct fields and a working "View on BottleBot" link
- [ ] `.env` secrets load correctly via `Settings` and are never written to `criteria.yaml`
- [ ] Daily digest scheduled correctly and sends at configured time
- [ ] `python -m src.cli score` prints a ranked table without sending any alert
- [ ] EOFY window modifier applies correctly in June
- [ ] Easter window is computed correctly for the given year via `dateutil.easter.easter`

---

## Known gotchas

- **90-day average is meaningless until Phase 1 has been running for a week+.** The first days of data will show everything as a "deal" because there's nothing to compare against. Add a guard: require at least 7 data points before scoring a product.
- **Retailer "was" prices are unreliable.** Dan Murphy's sometimes inflates the "was" price right before a sale. Always use the 90d average as the source of truth; show the retailer discount alongside for reference only.
- **Alert rate limits:** Discord webhooks and most apprise targets are happy with a message a second, but don't fire faster than that. Keep the 0.5s sleep between alerts in the immediate fire loop.
- **apprise body format is per-call, not per-target.** Passing `body_format=apprise.NotifyFormat.MARKDOWN` to `.notify()` renders markdown links/bold for Discord and any other target that supports it; plain-text-only targets (e.g. SMS gateways) will just show the raw markdown, which is usually still readable.
- **Never commit `.env`.** Add `.env` to `.gitignore` — only `.env.example` (with placeholder values) should be committed. Webhook URLs are effectively bearer tokens.

---

*Previous: [Phase 1 — Foundation](./PHASE_1.md) · Next: [Phase 3 — Breadth](./PHASE_3.md)*
