# 🍺 BottleBot

> Automated deal scraper & alert engine for Australian bottle shops — built for the bulk-buying EOFY shopper.

![Phase](https://img.shields.io/badge/phase-3%20of%204-blue)
![Phase 1](https://img.shields.io/badge/phase%201%20foundation-✅%20complete-brightgreen)
![Phase 2](https://img.shields.io/badge/phase%202%20intelligence-✅%20complete-brightgreen)
![Phase 3](https://img.shields.io/badge/phase%203%20breadth-✅%20complete-brightgreen)
![Phase 4](https://img.shields.io/badge/phase%204%20UX-🚧%20planned-yellow)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

**aka** *DealDiver · SalesSommelier · CaskCrawler · PriceProof*

---

## What is this?

BottleBot monitors Dan Murphy's, BWS, Liquorland, First Choice, and other Australian bottle shops for deals that actually matter. It builds a price history database over time so it can distinguish a genuine 40% EOFY discount from a retailer inflating their "was" price the week before a sale.

You configure your own criteria — minimum discount, cost-per-litre thresholds, category weights, brand allowlists — and BottleBot fires an alert only when something clears your bar. No noise, just signal.

Runs as a standalone Docker project — `docker compose up` and you're scraping — with alerts sent via [apprise](https://github.com/caronc/apprise), Discord being the primary channel (ntfy, email, and 100+ other services also supported).

---

## Core features

| Feature | Description |
|---|---|
| **Price history DB** | SQLite stores every scraped price with timestamp. Calculates real discount vs 90-day rolling average, not the retailer's "was" price. |
| **Deal scoring engine** | Weighted score per deal: discount depth × category weight × CPL rating × bulk-buy value. Fully configurable formula in YAML. |
| **User-configured criteria** | Min discount %, absolute $ saving, CPL threshold, category weights, brand allowlist/blocklist, min stock signal. |
| **Multi-channel alerts** | Discord (primary), plus ntfy, email, and 100+ other services via apprise. Fires when score clears threshold. Daily digest or immediate hot-deal mode. Alerts link to both the retailer product page and the BottleBot dashboard. |
| **Sale calendar awareness** | Pre-loaded AU retail calendar (EOFY June, Boxing Day, Easter). Tightens thresholds during sale windows. |
| **Price trend charts** | Per-product price history in alert payload or web UI. See if "50% off" is off a fake inflated RRP. |
| **Bulk-buy calculator** | Cost for 6/12/24 units, storage cost estimate, break-even vs normal retail. |
| **Watchlist** | Named products or categories. Fires immediately when a watchlist item hits any positive deal score. |

---

## Data sources

| Retailer | Method | Notes |
|---|---|---|
| Dan Murphy's | Playwright scraper | JS-rendered SPA; product & deals pages well-structured |
| BWS | Scraper + unofficial API | Shares Endeavour Group backend with Dan Murphy's |
| Liquorland | Scraper | Coles Group; similar patterns to FLC |
| First Choice Liquor | Scraper | Coles Group |
| CellarMasters | Scraper / member API | Wine club pricing available with membership |
| Vintage Cellars | Scraper | Coles Group |

Phase 1 builds Dan Murphy's first; Phase 3 adds the rest. Further sources (The Wine Collective,
GroceryRun/Staticice) are tracked as [Phase 5 ideas](./PHASE_4.md#potential-phase-5-ideas-future).

---

## Tech stack

```
Scraping      playwright · httpx · curl_cffi · beautifulsoup4 · tenacity
Storage       sqlite3 · SQLAlchemy · alembic
Scoring       pydantic · pyyaml · python-dateutil
Alerts        apprise (Discord primary · ntfy, email, etc.)
Config        python-dotenv · pydantic-settings
Scheduling    APScheduler · cron
Charts        plotly
Web UI        FastAPI · htmx · jinja2
CLI           typer · rich
Dev & test    pytest · respx · ruff
Deploy        Docker · Docker Compose
```

---

## Build phases

| Phase | Name | Focus | Status | Doc |
|---|---|---|---|---|
| **1** | Foundation | Scrape & store | ✅ Complete | [PHASE_1.md](./PHASE_1.md) |
| **2** | Intelligence | Score & alert | ✅ Complete | [PHASE_2.md](./PHASE_2.md) |
| **3** | Breadth | More sources | ✅ Complete | [PHASE_3.md](./PHASE_3.md) |
| **4** | UX | Dashboard & tools | 🚧 Planned | [PHASE_4.md](./PHASE_4.md) |

---

## Project structure

```
bottlebot/
├── README.md
├── PHASE_1.md
├── PHASE_2.md
├── PHASE_3.md
├── PHASE_4.md
├── .env.example                # Template for secrets (webhook URLs, API keys)
├── requirements.txt
├── pyproject.toml              # ruff + pytest config
├── config/
│   └── criteria.yaml          # User deal criteria & weights (no secrets)
├── src/
│   ├── cli.py                  # typer CLI: scrape, score (dry-run)
│   ├── run_scoring.py          # Scoring + alert pipeline (Phase 2)
│   ├── config/
│   │   └── settings.py        # pydantic-settings, loads .env
│   ├── scrapers/
│   │   ├── base.py            # Abstract scraper interface
│   │   ├── danmurphys.py
│   │   ├── bws.py
│   │   └── ...
│   ├── db/
│   │   ├── engine.py          # Shared SQLAlchemy engine (reads DB_PATH)
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── writer.py          # upsert_product — dedup & price-history writes
│   │   ├── matching.py        # Cross-retailer product matching (Phase 3)
│   │   └── migrations/        # Alembic migrations
│   ├── scoring/
│   │   ├── engine.py          # Deal scoring logic
│   │   └── criteria.py        # Criteria loader & validator
│   ├── alerts/
│   │   ├── notify.py          # apprise-based alerts (Discord primary)
│   │   └── digest.py          # Daily digest builder
│   ├── calendar.py            # AU sale calendar awareness
│   ├── scheduler.py           # APScheduler setup
│   └── web/                   # Phase 4 FastAPI UI
├── tests/
├── docker-compose.yml
└── Dockerfile
```

---

## Configuration (quick look)

```yaml
# config/criteria.yaml — shareable, no secrets
alerts:
  min_deal_score: 65          # 0-100 score threshold to fire alert
  immediate_threshold: 85     # Score at which to bypass digest and alert immediately
  digest_time: "08:00"        # Daily digest send time (AEST)

web:
  base_url: "http://localhost:8080"   # Used to build "View on BottleBot" links in alerts

scoring:
  weights:
    real_discount_pct: 0.35   # Weight: how deep the discount is vs 90-day average
    cpl_rating:        0.30   # Weight: cost per litre vs category average
    bulk_value:        0.20   # Weight: savings increase when buying 12+
    category_pref:     0.15   # Weight: personal category preference multiplier

categories:
  whisky:     1.4             # Multiplier — you care more about whisky
  wine_red:   1.2
  gin:        1.1
  beer:       0.8
  rtd:        0.5

thresholds:
  min_discount_pct:  20       # Ignore anything under 20% off
  min_saving_aud:    10       # Ignore anything saving less than $10
  max_cpl_aud:                # Max $/L by category
    whisky: 60
    wine_red: 25
    beer:   8
    default: 30

watchlist:
  products:
    - "Johnnie Walker Black"
    - "Penfolds Bin 389"
  categories: []              # e.g. ["whisky"] — any deal in these categories fires immediately

brands:
  blocklist:
    - "Black Douglas"         # Never alert on these
  allowlist: []               # Empty = all brands allowed
```

Secrets (Discord webhook URL, BWS API key, etc.) live in a separate `.env` file, loaded via
`pydantic-settings` — see [PHASE_2.md](./PHASE_2.md#notification-secrets-env).

---

## Deployment

BottleBot runs as a standalone Docker Compose project — no external infrastructure required.

```bash
# Start the stack
docker compose up -d

# Run a manual scrape
docker exec bottlebot python -m src.cli scrape --source danmurphys

# Check deal scores today without sending alerts
docker exec bottlebot python -m src.cli score --top 20
```

Alerts go out via [apprise](https://github.com/caronc/apprise), with Discord as the primary
channel — ntfy, email, and 100+ other services can be added as extra targets. See
[PHASE_2.md](./PHASE_2.md) for full alert configuration.

---

## Why not just use a price tracker app?

- No existing AU tool covers bottle shops with real price history (not retailer "was" prices)
- No tool lets you weight by category, CPL, or bulk-buy value
- No tool sends Discord alerts that link straight back to your own price-history dashboard
- This is more fun

---

## Licence

MIT. Drink responsibly. Buy irresponsibly (during sales).
