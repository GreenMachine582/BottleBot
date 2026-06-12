# 🍺 BottleBot

> Automated deal scraper & alert engine for Australian bottle shops — built for the bulk-buying EOFY shopper.

**aka** *DealDiver · SalesSommelier · CaskCrawler · PriceProof*

---

## What is this?

BottleBot monitors Dan Murphy's, BWS, Liquorland, First Choice, and other Australian bottle shops for deals that actually matter. It builds a price history database over time so it can distinguish a genuine 40% EOFY discount from a retailer inflating their "was" price the week before a sale.

You configure your own criteria — minimum discount, cost-per-litre thresholds, category weights, brand allowlists — and BottleBot fires an alert only when something clears your bar. No noise, just signal.

Runs as a standalone Docker project — `docker compose up` and you're scraping — with alerts via ntfy (self-hosted or ntfy.sh) and Discord as a fallback.

---

## Core features

| Feature | Description |
|---|---|
| **Price history DB** | SQLite stores every scraped price with timestamp. Calculates real discount vs 90-day rolling average, not the retailer's "was" price. |
| **Deal scoring engine** | Weighted score per deal: discount depth × category weight × CPL rating × bulk-buy value. Fully configurable formula in YAML. |
| **User-configured criteria** | Min discount %, absolute $ saving, CPL threshold, category weights, brand allowlist/blocklist, min stock signal. |
| **Multi-channel alerts** | ntfy (self-hosted), Discord webhook, email. Fires when score clears threshold. Daily digest or immediate hot-deal mode. |
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
| The Wine Collective | RSS / scraper | Good for wine-specific deals |
| GroceryRun / Staticice | Price comparison API | Cross-check & dedup |

---

## Tech stack

```
Scraping      playwright · requests · httpx · beautifulsoup4 · selectolax
Storage       sqlite3 · SQLAlchemy · alembic
Scoring       pydantic · pyyaml · pandas
Alerts        httpx · ntfy · discord-webhook · smtplib
Scheduling    APScheduler · cron
Charts        matplotlib · plotly
Web UI        FastAPI · htmx · jinja2
Deploy        Docker · Docker Compose
```

---

## Build phases

| Phase | Name | Focus | Doc |
|---|---|---|---|
| **1** | Foundation | Scrape & store | [PHASE_1.md](./PHASE_1.md) |
| **2** | Intelligence | Score & alert | [PHASE_2.md](./PHASE_2.md) |
| **3** | Breadth | More sources | [PHASE_3.md](./PHASE_3.md) |
| **4** | UX | Dashboard & tools | [PHASE_4.md](./PHASE_4.md) |

---

## Project structure

```
bottlebot/
├── README.md
├── PHASE_1.md
├── PHASE_2.md
├── PHASE_3.md
├── PHASE_4.md
├── config/
│   └── criteria.yaml          # User deal criteria & weights
├── bottlebot/
│   ├── scrapers/
│   │   ├── base.py            # Abstract scraper interface
│   │   ├── danmurphys.py
│   │   ├── bws.py
│   │   └── ...
│   ├── db/
│   │   ├── models.py          # SQLAlchemy models
│   │   └── migrations/        # Alembic migrations
│   ├── scoring/
│   │   ├── engine.py          # Deal scoring logic
│   │   └── criteria.py        # Criteria loader & validator
│   ├── alerts/
│   │   ├── ntfy.py
│   │   ├── discord.py
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
# config/criteria.yaml
alerts:
  min_deal_score: 65          # 0-100 score threshold to fire alert
  immediate_threshold: 85     # Score at which to bypass digest and alert immediately
  digest_time: "08:00"        # Daily digest send time (AEST)

scoring:
  weights:
    discount_pct: 0.35        # Weight: how deep the discount is
    cpl_rating:   0.30        # Weight: cost per litre vs category average
    bulk_value:   0.20        # Weight: savings increase when buying 12+
    category:     0.15        # Weight: personal category preference multiplier

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
    wine:   25
    beer:   8

watchlist:
  - "Johnnie Walker Black"
  - "Penfolds Bin 389"
  - category: whisky          # Any whisky deal fires immediately

brands:
  blocklist:
    - "Black Douglas"         # Never alert on these
  allowlist: []               # Empty = all brands allowed
```

---

## Deployment

BottleBot runs as a standalone Docker Compose project — no external infrastructure required.

```bash
# Start the stack
docker compose up -d

# Run a manual scrape
docker exec bottlebot python -m bottlebot.scrapers.danmurphys --once

# Check deal scores today
docker exec bottlebot python -m bottlebot.scoring.engine --dry-run
```

Alerts via ntfy topic `bottlebot-deals` (self-hosted or ntfy.sh) with Discord as a fallback. See Phase 2 docs for full alert configuration.

---

## Why not just use a price tracker app?

- No existing AU tool covers bottle shops with real price history (not retailer "was" prices)
- No tool lets you weight by category, CPL, or bulk-buy value
- No tool integrates with self-hosted alert infrastructure (ntfy)
- This is more fun

---

## Licence

MIT. Drink responsibly. Buy irresponsibly (during sales).
