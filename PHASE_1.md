# Phase 1 — Foundation: Scrape & Store

> **Goal:** Get a Dan Murphy's scraper running on a schedule, persisting raw price data to a local SQLite database. No scoring, no alerts yet — just reliable, clean data collection.

**Estimated effort:** 1–2 weekends  
**Depends on:** nothing (greenfield)  
**Unlocks:** Phase 2 (scoring needs price history to work)

---

## Deliverables

- [ ] Dan Murphy's scraper (deals page + category pages) with `tenacity` retries on network calls
- [ ] SQLAlchemy models & Alembic migration baseline
- [ ] CLI runner (`python -m src.cli scrape --source danmurphys`) via typer
- [ ] APScheduler job running every 6 hours
- [ ] Basic deduplication (don't re-insert unchanged prices)
- [ ] Docker container + Compose file
- [ ] pytest suite covering the DB writer's dedup/price-change logic

---

## 1. Database schema

### Products table

Tracks canonical product identity — one row per unique product across all retailers.

```sql
CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    brand       TEXT,
    category    TEXT,           -- 'whisky', 'wine_red', 'beer', etc.
    subcategory TEXT,           -- 'single_malt', 'ipa', etc.
    volume_ml   INTEGER,        -- normalised volume for CPL calc
    abv         REAL,           -- alcohol by volume %
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Retailer products table

One row per product-per-retailer. Handles the same product being sold at multiple retailers with different SKUs and URLs.

```sql
CREATE TABLE retailer_products (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id),
    retailer        TEXT NOT NULL,  -- 'danmurphys', 'bws', etc.
    retailer_sku    TEXT,
    url             TEXT NOT NULL,
    image_url       TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Price history table

Append-only log. Every scrape run inserts a row only if the price has changed since last observation.

```sql
CREATE TABLE price_history (
    id                  INTEGER PRIMARY KEY,
    retailer_product_id INTEGER REFERENCES retailer_products(id),
    price_aud           REAL NOT NULL,
    was_price_aud       REAL,           -- retailer's stated "was" price (often fake)
    in_stock            BOOLEAN DEFAULT TRUE,
    on_sale             BOOLEAN DEFAULT FALSE,
    promo_label         TEXT,           -- e.g. "EOFY Sale", "Mix Any 6"
    scraped_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Scrape runs table

Audit log for scheduler health monitoring.

```sql
CREATE TABLE scrape_runs (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  DATETIME,
    finished_at DATETIME,
    status      TEXT,           -- 'success', 'partial', 'failed'
    products_seen   INTEGER DEFAULT 0,
    prices_inserted INTEGER DEFAULT 0,
    error_msg   TEXT
);
```

### SQLAlchemy models (`src/db/models.py`)

```python
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship

class Base(DeclarativeBase):
    pass

class Product(Base):
    __tablename__ = "products"
    id          = Column(Integer, primary_key=True)
    name        = Column(String, nullable=False)
    brand       = Column(String)
    category    = Column(String)
    subcategory = Column(String)
    volume_ml   = Column(Integer)
    abv         = Column(Float)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    retailer_products = relationship("RetailerProduct", back_populates="product")

class RetailerProduct(Base):
    __tablename__ = "retailer_products"
    id              = Column(Integer, primary_key=True)
    product_id      = Column(Integer, ForeignKey("products.id"))
    retailer        = Column(String, nullable=False)
    retailer_sku    = Column(String)
    url             = Column(Text, nullable=False)
    image_url       = Column(Text)
    created_at      = Column(DateTime, default=datetime.utcnow)
    product         = relationship("Product", back_populates="retailer_products")
    price_history   = relationship("PriceHistory", back_populates="retailer_product")

class PriceHistory(Base):
    __tablename__ = "price_history"
    id                  = Column(Integer, primary_key=True)
    retailer_product_id = Column(Integer, ForeignKey("retailer_products.id"))
    price_aud           = Column(Float, nullable=False)
    was_price_aud       = Column(Float)
    in_stock            = Column(Boolean, default=True)
    on_sale             = Column(Boolean, default=False)
    promo_label         = Column(String)
    scraped_at          = Column(DateTime, default=datetime.utcnow)
    retailer_product    = relationship("RetailerProduct", back_populates="price_history")

class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    id              = Column(Integer, primary_key=True)
    source          = Column(String, nullable=False)
    started_at      = Column(DateTime)
    finished_at     = Column(DateTime)
    status          = Column(String)
    products_seen   = Column(Integer, default=0)
    prices_inserted = Column(Integer, default=0)
    error_msg       = Column(Text)
```

### Shared engine (`src/db/engine.py`)

A single SQLAlchemy engine, reused by the scheduler, scoring pipeline, CLI, and web UI, so they
all read and write the same SQLite file. It respects the `DB_PATH` env var set in
`docker-compose.yml` — without this, code defaulting to `sqlite:///bottlebot.db` would write to
`/app/bottlebot.db` inside the container instead of the `/app/data/bottlebot.db` path on the
mounted volume, and the database would be lost every time the container is rebuilt.

```python
# src/db/engine.py
import os
from sqlalchemy import create_engine

DB_PATH = os.environ.get("DB_PATH", "bottlebot.db")
engine = create_engine(f"sqlite:///{DB_PATH}")
```

### Schema migrations (Alembic)

`Base.metadata.create_all(engine)` (used in the scheduler below) is enough to get the tables
created for local development. Set up Alembic once you're ready to evolve the schema across
machines/containers without dropping data:

```bash
alembic init src/db/migrations
```

In the generated `src/db/migrations/env.py`, point `sqlalchemy.url` at the same `DB_PATH`
used by `src/db/engine.py`:

```python
# src/db/migrations/env.py (edit)
from src.db.engine import DB_PATH
config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")
```

Then generate and apply the baseline migration:

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

---

## 2. Base scraper interface

All retailer scrapers implement this interface. Makes Phase 3 (adding sources) a drop-in extension.

```python
# src/scrapers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

@dataclass
class ScrapedProduct:
    retailer: str
    retailer_sku: str
    url: str
    name: str
    brand: str | None
    category: str | None
    volume_ml: int | None
    abv: float | None
    price_aud: float
    was_price_aud: float | None
    in_stock: bool
    on_sale: bool
    promo_label: str | None
    image_url: str | None

class BaseScraper(ABC):
    retailer: str = ""

    @abstractmethod
    def scrape_deals(self) -> Iterator[ScrapedProduct]:
        """Yield products currently on deal / in the deals section."""
        ...

    @abstractmethod
    def scrape_category(self, category: str) -> Iterator[ScrapedProduct]:
        """Yield all products in a given category (for baseline price tracking)."""
        ...

    def scrape_all(self) -> Iterator[ScrapedProduct]:
        """Default: scrape deals only. Override for full catalogue."""
        yield from self.scrape_deals()
```

---

## 3. Dan Murphy's scraper

Dan Murphy's is a React SPA — requires Playwright for JS rendering. The deals page and category pages are the primary targets.

```python
# src/scrapers/danmurphys.py
import re
from typing import Iterator
from playwright.sync_api import sync_playwright, Page
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import BaseScraper, ScrapedProduct

DEALS_URL = "https://www.danmurphys.com.au/dm/page/deals"
CATEGORY_URLS = {
    "whisky": "https://www.danmurphys.com.au/spirits/whisky",
    "wine_red": "https://www.danmurphys.com.au/wine/red-wine",
    "beer":   "https://www.danmurphys.com.au/beer",
    "gin":    "https://www.danmurphys.com.au/spirits/gin",
}

class DanMurphysScraper(BaseScraper):
    retailer = "danmurphys"

    def _parse_product_card(self, card) -> ScrapedProduct | None:
        try:
            name = card.query_selector("[data-testid='product-name']").inner_text().strip()
            price_text = card.query_selector("[data-testid='product-price']").inner_text()
            price_aud = float(re.sub(r"[^\d.]", "", price_text))

            was_el = card.query_selector("[data-testid='product-was-price']")
            was_price = float(re.sub(r"[^\d.]", "", was_el.inner_text())) if was_el else None

            url_el = card.query_selector("a[href]")
            url = "https://www.danmurphys.com.au" + url_el.get_attribute("href") if url_el else ""

            promo_el = card.query_selector("[data-testid='product-promo-label']")
            promo_label = promo_el.inner_text().strip() if promo_el else None

            img_el = card.query_selector("img")
            image_url = img_el.get_attribute("src") if img_el else None

            # Extract volume from name (e.g. "700mL", "1.125L")
            vol_match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|mL|L|l)", name)
            volume_ml = None
            if vol_match:
                val, unit = float(vol_match.group(1)), vol_match.group(2).lower()
                volume_ml = int(val * 1000 if unit == "l" else val)

            return ScrapedProduct(
                retailer=self.retailer,
                retailer_sku=url.split("/")[-1] if url else "",
                url=url,
                name=name,
                brand=None,     # Phase 3: extract from name or API
                category=None,  # Phase 3: map from URL path
                volume_ml=volume_ml,
                abv=None,
                price_aud=price_aud,
                was_price_aud=was_price,
                in_stock=True,
                on_sale=was_price is not None,
                promo_label=promo_label,
                image_url=image_url,
            )
        except Exception:
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _goto(self, page: Page, url: str):
        """Navigate with retries — Dan Murphy's occasionally times out under load."""
        page.goto(url, wait_until="networkidle", timeout=30000)

    def _scrape_page(self, page: Page, url: str) -> Iterator[ScrapedProduct]:
        self._goto(page, url)
        # Scroll to load lazy content
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(800)

        cards = page.query_selector_all("[data-testid='product-card']")
        for card in cards:
            product = self._parse_product_card(card)
            if product:
                yield product

        # Pagination: click "Load more" if present
        load_more = page.query_selector("[data-testid='load-more-button']")
        if load_more:
            load_more.click()
            page.wait_for_timeout(1500)
            yield from self._scrape_page(page, page.url)

    def scrape_deals(self) -> Iterator[ScrapedProduct]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"Accept-Language": "en-AU"})
            yield from self._scrape_page(page, DEALS_URL)
            browser.close()

    def scrape_category(self, category: str) -> Iterator[ScrapedProduct]:
        url = CATEGORY_URLS.get(category)
        if not url:
            raise ValueError(f"Unknown category: {category}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            yield from self._scrape_page(page, url)
            browser.close()
```

> **Note on selectors:** Dan Murphy's periodically changes their `data-testid` attributes. Treat selector strings as the most likely thing to break. Consider storing them in a config file for easy maintenance.

---

## 4. Persistence layer

```python
# src/db/writer.py
from datetime import datetime
from sqlalchemy.orm import Session
from .models import Product, RetailerProduct, PriceHistory, ScrapeRun
from ..scrapers.base import ScrapedProduct

def upsert_product(session: Session, scraped: ScrapedProduct) -> tuple[RetailerProduct, bool]:
    """
    Find or create RetailerProduct. Returns (retailer_product, price_changed).
    Only inserts a new PriceHistory row if the price has actually changed.
    """
    rp = session.query(RetailerProduct).filter_by(
        retailer=scraped.retailer,
        url=scraped.url
    ).first()

    if not rp:
        product = Product(
            name=scraped.name,
            brand=scraped.brand,
            category=scraped.category,
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
```

---

## 5. Scheduler & CLI

```python
# src/scheduler.py
from apscheduler.schedulers.blocking import BlockingScheduler
from .scrapers.danmurphys import DanMurphysScraper
from .db.writer import upsert_product
from .db.models import ScrapeRun, Base
from .db.engine import engine
from sqlalchemy.orm import Session
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

Base.metadata.create_all(engine)

def run_scraper(scraper_cls, source_name: str):
    log.info(f"Starting scrape: {source_name}")
    run = ScrapeRun(source=source_name, started_at=datetime.utcnow(), status="running")
    with Session(engine) as session:
        session.add(run)
        session.commit()
        try:
            scraper = scraper_cls()
            seen = inserted = 0
            for product in scraper.scrape_deals():
                seen += 1
                _, changed = upsert_product(session, product)
                if changed:
                    inserted += 1
            session.commit()
            run.status = "success"
            run.products_seen = seen
            run.prices_inserted = inserted
        except Exception as e:
            run.status = "failed"
            run.error_msg = str(e)
            log.exception(f"Scrape failed: {source_name}")
        finally:
            run.finished_at = datetime.utcnow()
            session.commit()
    log.info(f"Done: {source_name} — {seen} seen, {inserted} new prices")

def main():
    scheduler = BlockingScheduler(timezone="Australia/Sydney")
    scheduler.add_job(
        run_scraper,
        "interval",
        hours=6,
        args=[DanMurphysScraper, "danmurphys"],
        next_run_time=datetime.now()  # Run immediately on start
    )
    log.info("BottleBot scheduler started. Running every 6 hours.")
    scheduler.start()

if __name__ == "__main__":
    main()
```

### CLI entrypoint

A small [typer](https://typer.tiangolo.com/) app gives a one-off scrape command for manual runs
and debugging, without waiting for the scheduler's next 6-hour tick. Phase 2 extends this same
app with a `score` command.

```python
# src/cli.py
import typer
from .scrapers.danmurphys import DanMurphysScraper
from .scheduler import run_scraper

app = typer.Typer(help="BottleBot CLI")

SCRAPERS = {
    "danmurphys": DanMurphysScraper,
}

@app.command()
def scrape(source: str = typer.Option("danmurphys", help="Scraper source to run")):
    """Run a one-off scrape for the given source."""
    scraper_cls = SCRAPERS.get(source)
    if not scraper_cls:
        typer.echo(f"Unknown source: {source}. Choices: {', '.join(SCRAPERS)}")
        raise typer.Exit(1)
    run_scraper(scraper_cls, source)

if __name__ == "__main__":
    app()
```

```bash
# Run a manual scrape outside the scheduler
python -m src.cli scrape --source danmurphys
```

---

## 6. Dependencies & tooling config

One `requirements.txt` at the repo root covers the whole project — later phases just append
to it. Pin exact versions with `pip freeze > requirements.txt` once Phase 1 is working locally;
the list below is the minimum set of top-level packages.

```txt
# requirements.txt

# Phase 1 — scraping & storage
playwright
tenacity
SQLAlchemy
alembic
APScheduler
typer

# Phase 2 — config, scoring & alerts
pydantic
pydantic-settings
python-dotenv
PyYAML
python-dateutil
apprise
rich

# Phase 3 — additional sources
httpx
curl_cffi
beautifulsoup4

# Phase 4 — web UI
fastapi
uvicorn[standard]
jinja2
plotly

# Dev & test
pytest
respx
ruff
```

Ruff and pytest settings live in `pyproject.toml` at the repo root:

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

## 7. Docker setup

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "-m", "src.scheduler"]
```

```yaml
# docker-compose.yml
services:
  bottlebot:
    build: .
    container_name: bottlebot
    restart: unless-stopped
    volumes:
      - ./data:/app/data        # SQLite DB persists here
      - ./config:/app/config    # criteria.yaml
    environment:
      - DB_PATH=/app/data/bottlebot.db
      - TZ=Australia/Sydney
```

---

## 8. Testing

The DB writer's dedup logic is the highest-value thing to test in Phase 1 — it's pure
SQLAlchemy against an in-memory SQLite DB, so no Playwright/browser needed.

```python
# tests/test_writer.py
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
```

```bash
pytest tests/ -v
```

Run `ruff check .` and `ruff format .` before committing — both are fast enough to run on every save.

---

## Phase 1 acceptance criteria

- [ ] `docker compose up` starts the scheduler cleanly
- [ ] First scrape run completes, `scrape_runs` table shows `status = 'success'`
- [ ] `price_history` table has rows with real prices and timestamps
- [ ] Re-running scraper does NOT insert duplicate rows for unchanged prices
- [ ] A product whose price drops between runs gets a new `price_history` row
- [ ] `scrape_runs.products_seen` is > 0 and `prices_inserted` is > 0

---

## Known gotchas

- **Selector drift:** Dan Murphy's updates their React component `data-testid` names occasionally. Budget for a 1-hour fix every few months.
- **Rate limiting:** Add `page.wait_for_timeout(1000–2000ms)` between page navigations. Don't hammer at < 1s intervals.
- **Headless Chromium on ARM hosts:** Playwright's bundled Chromium is x86-only. On ARM64 hosts, install the system Chromium and point Playwright at it via `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser`.
- **Volume parsing:** Names like "700mL", "700 mL", "70cl", "1.125L" all appear in the wild. The regex handles mL/L but watch for cl (centilitre) variants on imported products.
- **tenacity retries and `session.commit()`:** the `@retry` on `_goto` only covers navigation — if a transient failure happens mid-page (e.g. a selector query throws), it propagates up to `run_scraper`'s `except` block and the whole run is marked `failed`. That's fine for Phase 1 (the next scheduled run picks it up), but don't be tempted to wrap the entire `scrape_deals()` generator in `@retry` — partial results would be re-yielded from the start and double-counted in `seen`/`inserted`.

---

*Next: [Phase 2 — Intelligence: Score & Alert](./PHASE_2.md)*
