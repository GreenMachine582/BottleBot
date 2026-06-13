# Phase 1 — Foundation: Scrape & Store

> **Goal:** Get a Dan Murphy's scraper running on a schedule, persisting raw price data to a local SQLite database. No scoring, no alerts yet — just reliable, clean data collection.

**Status:** ✅ Complete

**Estimated effort:** 1–2 weekends  
**Depends on:** nothing (greenfield)  
**Unlocks:** Phase 2 (scoring needs price history to work)

---

## Deliverables

- [x] Dan Murphy's scraper (deals page + category pages) with `tenacity` retries on network calls — [`src/scrapers/danmurphys.py`](./src/scrapers/danmurphys.py)
- [x] SQLAlchemy models & Alembic migration baseline — [`src/db/models.py`](./src/db/models.py), [`src/db/migrations/`](./src/db/migrations/)
- [x] CLI runner (`python -m src.cli scrape --source danmurphys`) via typer — [`src/cli.py`](./src/cli.py)
- [x] APScheduler job running every 6 hours — [`src/scheduler.py`](./src/scheduler.py)
- [x] Basic deduplication (don't re-insert unchanged prices) — [`src/db/writer.py`](./src/db/writer.py)
- [x] Docker container + Compose file — [`Dockerfile`](./Dockerfile), [`docker-compose.yml`](./docker-compose.yml)
- [x] pytest suite covering the DB writer's dedup/price-change logic — [`tests/test_writer.py`](./tests/test_writer.py)

---

## 1. Database schema

Four tables, defined as SQLAlchemy models in [`src/db/models.py`](./src/db/models.py):

- **`products`** — canonical product identity (`name`, `brand`, `category`, `subcategory`, `volume_ml`, `abv`), one row per unique product across all retailers.
- **`retailer_products`** — one row per product-per-retailer, linking a `Product` to a retailer's SKU, URL and image.
- **`price_history`** — append-only price log (`price_aud`, `was_price_aud`, `in_stock`, `on_sale`, `promo_label`, `scraped_at`). A new row is only inserted when the price actually changes (see [`src/db/writer.py`](./src/db/writer.py)).
- **`scrape_runs`** — audit log for scheduler health (`status`, `products_seen`, `prices_inserted`, `error_msg`).

### Shared engine

[`src/db/engine.py`](./src/db/engine.py) exposes a single SQLAlchemy `engine`, reused by the scheduler, CLI and (later) the scoring pipeline and web UI so they all read/write the same SQLite file. It calls `load_dotenv()` on import — the earliest-imported module across all entrypoints — so a local `.env` file (see [`.env.example`](./.env.example)) populates `DB_PATH`, `DANMURPHYS_MEMBER`, etc. before anything else reads `os.environ`. `DB_PATH` defaults to `bottlebot.db` but is set to `/app/data/bottlebot.db` in `docker-compose.yml` so the database lives on the mounted volume and survives container rebuilds.

### Schema migrations (Alembic)

Alembic is initialised under [`src/db/migrations/`](./src/db/migrations/). Its `env.py` points `sqlalchemy.url` at the same `DB_PATH` as `src/db/engine.py` and sets `target_metadata = Base.metadata` so `--autogenerate` can detect schema changes. For local dev, `Base.metadata.create_all(engine)` (called at scheduler startup) is enough to create tables from scratch; use `alembic revision --autogenerate -m "..."` / `alembic upgrade head` when evolving the schema on a machine that already has data.

---

## 2. Base scraper interface

[`src/scrapers/base.py`](./src/scrapers/base.py) defines the `ScrapedProduct` dataclass (the common shape every retailer scraper yields) and the `BaseScraper` ABC (`scrape_deals`, `scrape_category`, `scrape_all`). Every retailer scraper — Dan Murphy's now, others in Phase 3 — implements this interface, so the writer, scheduler and CLI never need to know which retailer they're talking to.

---

## 3. Dan Murphy's scraper

[`src/scrapers/danmurphys.py`](./src/scrapers/danmurphys.py) — Dan Murphy's is an Angular SPA, so it's scraped with Playwright (`sync_playwright`). Notable parts of the implementation:

- **Cloudflare evasion:** a realistic desktop `USER_AGENT`, viewport, `en-AU` locale/timezone, and `--disable-blink-features=AutomationControlled` keep headless Chromium from tripping Cloudflare's "Attention Required!" challenge. `_goto` also detects a challenge page by title and raises, so the `@retry` (tenacity, 3 attempts, exponential backoff) retries the navigation.
- **Bounded pagination:** `_extract_cards` clicks "Show N more" up to `MAX_LOAD_MORE_PAGES` (15) times, processing only newly-added `<product-card-view>` elements each pass and logging progress per page. `page.set_default_timeout(20000)` ensures no single Playwright call can hang forever.
- **Price extraction (`_extract_price_info`):** handles two card layouts — "member offer" cards (`.product-card-cost.bg-member-color`, with a separate non-member reference price) and plain cards (`.price-container`, with an optional multi-buy `.promo-price`). `DANMURPHYS_MEMBER` (below) picks which price becomes `price_aud` vs `was_price_aud` on member-offer cards.
- **Name/volume parsing (`_parse_product_card`):** the product `<img alt>` text is parsed with `SIZE_REPEAT_RE` (a repeated size token like "330ml 330ML" or "1l 1L" marks the name/description boundary), falling back to `SIZE_TOKEN_RE` (a single `<N>ML`/`<N>mL`/`<N>L` token) and finally `alt.split("...")[0]`. The image is looked up via `link_el.query_selector(SEL_PRODUCT_IMAGE)` so badge images (`alt="product badge"`) on "New"/"Catalogue Offers" cards aren't picked up instead.

### Selectors reference

All CSS/element selectors are centralised as `SEL_*` constants near the top of `danmurphys.py` so a DOM change only needs updating in one place. If a selector stops matching, the affected field comes back `None` (or `_parse_product_card` skips the card) — watch for a drop in `scrape_runs.products_seen`/`prices_inserted`, or many rows with `price_aud is None`.

| Constant | Selector | Targets | Spot-check on the live site |
| --- | --- | --- | --- |
| `SEL_PRODUCT_CARD` | `product-card-view` | One custom element per product tile on deals/category pages | DevTools → Elements, search for `<product-card-view>` |
| `SEL_LOAD_MORE` | `.infinite-loader__load-more-button` | "Show N more" infinite-scroll button | Scroll to the bottom of a category page; button should be visible/clickable |
| `SEL_PRODUCT_LINK` | `a[href]` | Product tile's link to its detail page — source of `url`/`retailer_sku` | Click a tile; the URL should match `href` |
| `SEL_PRODUCT_IMAGE` | `img` (scoped to `SEL_PRODUCT_LINK`) | Product image — `alt` text is parsed for name/volume | Inspect the `<img>` inside the product link; `alt` should still read "Name...SIZE description" |
| `SEL_MEMBER_PRICE_BOX` | `.product-card-cost.bg-member-color` | "MEMBER OFFER" price block (only on member-priced cards) | Find a card with a highlighted "Member" price |
| `SEL_MEMBER_PRICE` | `.card-price` (within `SEL_MEMBER_PRICE_BOX`) | Member price value | |
| `SEL_MEMBER_UNIT` | `.product-card-unit` (within `SEL_MEMBER_PRICE_BOX`) | Per-unit price text (e.g. "$/L") | |
| `SEL_MEMBER_OFFER_LABEL` | `.offer-txt` (within `SEL_MEMBER_PRICE_BOX`) | "MEMBER OFFER" label text | |
| `SEL_NON_MEMBER_PRICE` | `.offers-normal-tile .value` | Non-member reference price shown alongside a member offer | |
| `SEL_PRICE_CONTAINER` | `.price-container` | Regular (non-member-offer) price block | Find a card without a "Member" badge |
| `SEL_PRICE_VALUE` | `[itemprop='price'] .value` (within `SEL_PRICE_CONTAINER`) | Price value | |
| `SEL_PROMO_PRICE` | `.promo-price` (within `SEL_PRICE_CONTAINER`) | Multi-buy promo text (e.g. "OFFER $121.90 for 2") | |

### `DANMURPHYS_MEMBER`

Configured via `.env` (copy [`.env.example`](./.env.example)) or `docker-compose.yml`. By default (`false`/unset), `price_aud` is the non-member price. Set to `true`/`1`/`yes` to record the member price as `price_aud`, with the non-member price stored in `was_price_aud`. Cards without a member-offer split are unaffected.

---

## 4. Persistence layer

[`src/db/writer.py`](./src/db/writer.py) — `upsert_product(session, scraped)` finds or creates the `Product`/`RetailerProduct` pair for a `ScrapedProduct`, then inserts a new `PriceHistory` row only if `price_aud` differs from the most recent observation. Returns `(retailer_product, price_changed)`.

---

## 5. Scheduler & CLI

- [`src/scheduler.py`](./src/scheduler.py) — `run_scraper(scraper_cls, source_name)` runs a scraper, records a `ScrapeRun` (status/seen/inserted/error), and calls `upsert_product` for each product. `main()` runs `DanMurphysScraper` via APScheduler's `BlockingScheduler` every 6 hours, with an immediate first run.
- [`src/cli.py`](./src/cli.py) — a `typer` app exposing `python -m src.cli scrape --source danmurphys` for one-off manual runs without waiting for the scheduler's next tick.

---

## 6. Dependencies & tooling config

[`requirements.txt`](./requirements.txt) at the repo root covers all four phases — Phase 1 added `playwright`, `tenacity`, `SQLAlchemy`, `alembic`, `APScheduler` and `typer`, plus `python-dotenv` for `.env` support. Ruff and pytest config live in [`pyproject.toml`](./pyproject.toml).

---

## 7. Docker setup

[`Dockerfile`](./Dockerfile) and [`docker-compose.yml`](./docker-compose.yml) build the scraper image (including Playwright's Chromium) and run `src.scheduler` on a 6-hour interval. `docker-compose.yml` mounts `./data` for the SQLite file and sets `DB_PATH`, `TZ` and `DANMURPHYS_MEMBER`. For local (non-Docker) runs, copy `.env.example` to `.env` to set the same variables.

---

## 8. Testing

[`tests/test_writer.py`](./tests/test_writer.py) covers the dedup logic against an in-memory SQLite DB: a first scrape inserts a `PriceHistory` row, an unchanged price doesn't insert again, and a price change inserts a new row. Run with `pytest tests/ -v`; `ruff check .` / `ruff format .` before committing.

---

## Phase 1 acceptance criteria

- [x] `docker compose up` starts the scheduler cleanly
- [x] First scrape run completes, `scrape_runs` table shows `status = 'success'`
- [x] `price_history` table has rows with real prices and timestamps
- [x] Re-running scraper does NOT insert duplicate rows for unchanged prices
- [x] A product whose price drops between runs gets a new `price_history` row
- [x] `scrape_runs.products_seen` is > 0 and `prices_inserted` is > 0

---

## Known gotchas

- **Cloudflare bot detection:** headless Chromium with default settings gets served a Cloudflare "Attention Required!" challenge instead of the site. Fixed with a realistic `USER_AGENT`, viewport, `en-AU` locale/timezone, `--disable-blink-features=AutomationControlled`, and a challenge-page check in `_goto` so `@retry` can retry the navigation.
- **Infinite/hung scrapes:** the original recursive "load more → re-scrape from scratch" pagination could hang forever if the load-more button never disappeared, and a stuck Playwright call (e.g. `click()`) had no timeout — this once left a scrape running for 10+ hours. Fixed with bounded iteration (`MAX_LOAD_MORE_PAGES`) and `page.set_default_timeout(20000)`.
- **`<img alt>` parsing is fragile:** Dan Murphy's alt text mixes the product name, size and a marketing description with no consistent delimiter, and litre-sized products repeat the size token in different cases ("1l 1L", "700ml 700ml"). `SIZE_REPEAT_RE` → `SIZE_TOKEN_RE` → fallback splitting handles the cases seen so far. Badge images (`alt="product badge"`) on "New"/"Catalogue Offers" cards must be excluded by scoping the image lookup to the product link, not the whole card.
- **Two price layouts:** "MEMBER OFFER" cards and plain cards use completely different DOM structures for price — `_extract_price_info` must check `.product-card-cost.bg-member-color` before falling back to `.price-container`.
- **Selector drift:** Dan Murphy's periodically changes the class names/structure above. All selectors are centralised as `SEL_*` constants in `danmurphys.py` — see the [Selectors reference](#selectors-reference) table for what each targets and how to spot-check it in devtools when `scrape_runs.products_seen` drops or prices come back `None`.
- **`.env` / `DANMURPHYS_MEMBER`:** `load_dotenv()` must run before any module reads `os.environ`, so it's called once in `src/db/engine.py` rather than in each entrypoint.
- **ARM hosts:** Playwright's bundled Chromium is x86-only. On ARM64 hosts, install system Chromium and set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser`.

---

*Next: [Phase 2 — Intelligence: Score & Alert](./PHASE_2.md)*
