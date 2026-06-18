# Phase 4 — UX: Dashboard & Tools

> **Goal:** A simple self-hosted web UI to browse current deals, manage your watchlist and criteria, view price history charts, and run the bulk-buy calculator. FastAPI backend with htmx-powered frontend, styled with Bootstrap 5 — no JavaScript framework required.

**Status:** ✅ Complete

**Estimated effort:** 2–3 weekends
**Depends on:** Phases 1–3 (all data, scoring, and sources must be running)
**Access:** Local network only — `http://<host-ip>:8080`. Not exposed to the public internet.

---

## Deliverables

- [x] FastAPI app with Jinja2 templates — [`src/web/app.py`](./src/web/app.py)
- [x] Shared Jinja2Templates instance — [`src/web/templating.py`](./src/web/templating.py)
- [x] Dashboard: today's top deals, sorted by score — [`src/web/routes/dashboard.py`](./src/web/routes/dashboard.py), [`src/web/templates/dashboard.html`](./src/web/templates/dashboard.html)
- [x] Deal detail page: score breakdown, price history chart, cross-retailer comparison, bulk-buy calc — [`src/web/routes/deals.py`](./src/web/routes/deals.py), [`src/web/templates/deal.html`](./src/web/templates/deal.html)
- [x] Watchlist manager: add/remove products and categories via UI — [`src/web/routes/watchlist.py`](./src/web/routes/watchlist.py), [`src/web/templates/watchlist.html`](./src/web/templates/watchlist.html)
- [x] Criteria editor: adjust alert thresholds without editing YAML by hand — [`src/web/routes/criteria.py`](./src/web/routes/criteria.py), [`src/web/templates/criteria.html`](./src/web/templates/criteria.html)
- [x] Price history chart (Plotly, rendered inline via `pio.to_html`) — [`src/web/routes/deals.py`](./src/web/routes/deals.py)
- [x] Bulk-buy calculator with htmx quantity slider — [`src/web/templates/_bulkcalc_table.html`](./src/web/templates/_bulkcalc_table.html)
- [x] EOFY/sale calendar indicator in every page header
- [x] Scrape run status / health panel — [`src/web/routes/health.py`](./src/web/routes/health.py), [`src/web/templates/health.html`](./src/web/templates/health.html)
- [x] Docker split into scraper + web services — [`docker-compose.yml`](./docker-compose.yml)
- [x] Dashboard warns when `web.base_url` doesn't match the actual request origin
- [x] Smoke tests for all routes — [`tests/test_web_routes.py`](./tests/test_web_routes.py)

---

## 1. App structure

```
src/web/
├── app.py              # FastAPI app, static mount, current_sale_window() Jinja2 global
├── templating.py       # Single Jinja2Templates instance shared by all routes
├── routes/
│   ├── dashboard.py    # GET /
│   ├── deals.py        # GET /deals/{id} · GET /deals/{id}/bulkcalc (htmx fragment)
│   ├── watchlist.py    # GET /watchlist · POST /watchlist/add · POST /watchlist/remove
│   ├── criteria.py     # GET /criteria · POST /criteria
│   └── health.py       # GET /health
├── templates/
│   ├── base.html       # Bootstrap 5 layout, navbar, sale banner, local-datetime JS
│   ├── dashboard.html
│   ├── deal.html
│   ├── _bulkcalc_table.html  # htmx partial — just the bulk-buy table rows
│   ├── watchlist.html
│   ├── criteria.html
│   └── health.html
└── static/
    └── style.css       # Custom overrides (Bootstrap 5 handles the rest)
```

Run locally with: `uvicorn src.web.app:app --host 0.0.0.0 --port 8080`

---

## 2. Templates and styling

[`src/web/templates/base.html`](./src/web/templates/base.html) — [Bootstrap 5](https://getbootstrap.com/) (`data-bs-theme="dark"`) loaded from CDN, with a Bootstrap navbar, alert-based sale banner, and footer. htmx also loaded from CDN — no build step, no bundler. The base template calls `current_sale_window()` (a Jinja2 global registered in `app.py`) so the sale banner appears on every page without each route having to pass it.

[`src/web/static/style.css`](./src/web/static/style.css) adds a minimal layer on top of Bootstrap:

| Class | Used for |
|---|---|
| `.sale-banner` | Full-width amber bar when a sale window is active |
| `tr.hot` | Dashboard rows with score ≥ 85 (orange tint) |
| `tr.watchlist` | Dashboard rows for watchlisted items (green tint) |
| `tr.best-price` | Deal detail cross-retailer table — cheapest retailer |
| `tr.highlight` | Bulk-buy table — qty 12 row and the slider's current qty |
| `.base-url-warning` | Yellow-bordered article when `web.base_url` mismatches |
| `.error-banner` | Red-bordered article for criteria validation errors |
| `tr.failed-run` | Health page rows for failed scrape runs |

---

## 3. Dashboard (`/`)

[`src/web/routes/dashboard.py`](./src/web/routes/dashboard.py) — loads `criteria.yaml`, runs `ScoringEngine.score_all_current_deals()`, and renders up to 50 deals sorted by score. Two banners are conditionally shown:

- **Sale window banner** — driven by `current_sale_window()` in `base.html`
- **Base-URL mismatch warning** — compares `criteria.web.base_url` against `request.base_url`; shown when they differ so Discord "View on BottleBot" links can be fixed before they break on other devices

---

## 4. Deal detail (`/deals/{id}`)

[`src/web/routes/deals.py`](./src/web/routes/deals.py) — fetches the `RetailerProduct`, its full `PriceHistory`, the cross-retailer comparison (from `compare_product_across_retailers()`), and optionally a `DealScore` (from `ScoringEngine.score_deal()`) for the score breakdown panel.

**Price history chart** — built with Plotly (`go.Scatter`, dark transparent background, green `#5BCAA5` line) and embedded as an inline HTML div via `pio.to_html(..., include_plotlyjs="cdn")`. Only rendered when there are at least 2 history points.

**Bulk-buy calculator** — initial render includes `_bulkcalc_table.html` with quantities `[1, 6, 12, 24]`. A range slider (`min=1`, `max=48`, `value=12`) uses `hx-get=/deals/{id}/bulkcalc`, `hx-trigger="input changed delay:150ms"`, `hx-target=#bulk-table` to swap the table fragment on change. The endpoint adds the slider's current qty to the fixed rows (deduped and sorted) so you always see it alongside the standard quantities.

**Session expunge** — SQLAlchemy objects are expunged from the session before the `with Session(engine)` block exits so Jinja2 can access their attributes after the session has closed.

---

## 5. Watchlist manager (`/watchlist`)

[`src/web/routes/watchlist.py`](./src/web/routes/watchlist.py) — reads and writes `config/criteria.yaml` directly via `yaml.safe_load` / `yaml.dump`. POST `/watchlist/add` appends a product name or category (stripped of whitespace, deduped). POST `/watchlist/remove` removes it. Both redirect back to GET `/watchlist` (PRG pattern). Changes take effect on the next scoring run — no restart needed.

---

## 6. Criteria editor (`/criteria`)

[`src/web/routes/criteria.py`](./src/web/routes/criteria.py) — form for editing the four most frequently tuned values: `min_deal_score`, `immediate_threshold`, `min_discount_pct`, `min_saving_aud`. The POST handler reads the YAML, applies the changes, validates the result through `Criteria.model_validate(raw)` before writing — an invalid input (e.g. a string where a float is expected) re-renders the form with a validation error and leaves `criteria.yaml` untouched. Category weights, CPL caps, and brand lists are still edited directly in the YAML file.

---

## 7. Health panel (`/health`)

[`src/web/routes/health.py`](./src/web/routes/health.py) — queries the last 30 `ScrapeRun` rows ordered by `started_at` desc. The table shows source, start time (rendered in the viewer's browser-local timezone via the `data-utc` mechanism described in §2), duration in seconds, products seen, new prices inserted, and a ✅/❌/⏳ status badge. Failed runs show their `error_msg` in a collapsible `<details>` element.

---

## 8. Docker Compose

[`docker-compose.yml`](./docker-compose.yml) — two services sharing a volume-mounted SQLite DB and `config/` directory:

| Service | Command | Port |
|---|---|---|
| `bottlebot-scraper` | `python -m src.scheduler` | — |
| `bottlebot-web` | `uvicorn src.web.app:app --host 0.0.0.0 --port 8080` | 8080 |

The `BOTTLEBOT_BWS_SUBSCRIPTION_KEY` env var was also wired into the scraper service in this phase.

---

## 9. Testing

[`tests/test_web_routes.py`](./tests/test_web_routes.py) — 9 smoke tests using `fastapi.testclient.TestClient`. A `module`-scoped fixture creates a temp SQLite DB, creates all tables, writes a minimal `criteria.yaml` to a temp directory, and patches the `engine` attribute in each route module (and `CRITERIA_PATH` in the watchlist/criteria modules) to point at the temp resources. The patch works because route functions look up `engine` from their own module's global namespace at call time — reassigning `mod.engine = test_engine` in the fixture takes effect before any request is made.

Tests cover: dashboard loads, empty-state message, health panel showing a seeded `ScrapeRun`, watchlist add/remove round-trip, criteria form load, criteria save, and 404 responses for unknown deal IDs.

`python-multipart` was added to `requirements.txt` — FastAPI requires it to parse `Form(...)` fields.

---

## Phase 4 acceptance criteria

- [x] `docker compose up` starts both scraper and web containers cleanly
- [x] Dashboard loads at `http://localhost:8080` and shows ranked deals
- [x] Deal detail page shows price history chart for a product with 2+ price points
- [x] Cross-retailer comparison section shows prices from matched products
- [x] Bulk-buy table calculates correctly; htmx slider updates it without a full page reload
- [x] Watchlist add/remove persists to `criteria.yaml` and immediately affects next score run
- [x] Criteria editor saves valid changes and rejects invalid ones without writing the file
- [x] Health page shows last 30 scrape runs with status and duration
- [x] Sale banner appears in the header during active sale windows (EOFY, Boxing Day, etc.)
- [x] Base-URL mismatch banner appears when `web.base_url` doesn't match the actual request origin
- [x] All 9 smoke tests pass

---

## Known gotchas

- **Starlette 1.x `TemplateResponse` API.** From Starlette 1.0, the signature is `TemplateResponse(request, name, context={})` — `request` is the first positional arg and is **not** included in the context dict. The old form `TemplateResponse(name, {"request": request, ...})` silently passes the context dict as `name`, which causes a `TypeError: unhashable type: 'dict'` deep in Jinja2's LRU cache. All route files use the new form.
- **`yaml.dump` drops comments.** The watchlist and criteria POST handlers write back to `criteria.yaml` via `yaml.dump`, which doesn't preserve inline comments. Category weights, CPL caps, and brand lists edited by hand will lose their comments on the next UI save. Use `ruamel.yaml` if comment preservation matters.
- **Session expunge before template render.** SQLAlchemy lazy-loads relationships on attribute access. If an ORM object is accessed after its session closes, you get a `DetachedInstanceError`. The deal detail route calls `session.expunge_all()` before the `with Session(engine)` block exits so Jinja2 can safely walk `rp.product` and other relationships in the template.
- **Plotly CDN dependency.** The price history chart loads `plotly.js` from `cdn.plot.ly`. On an air-gapped host, either bundle plotly (`include_plotlyjs=True` in `pio.to_html`) or serve it from `src/web/static/`.
- **`python-multipart` required for forms.** FastAPI doesn't install it by default — any `Form(...)` parameter silently fails at startup with a `RuntimeError` if it's missing. It's in `requirements.txt` and the `Dockerfile` will pick it up on the next build.

---

## Potential Phase 5 ideas (future)

- **Richer push notifications** — Discord's mobile app already covers push via the webhook; Phase 5 could attach product images to apprise notifications (`apobj.notify(..., attach=...)`) for Discord, Pushover, etc.
- **Automated cart builder** — given a scored deal list, generate a shareable link to a Dan Murphy's cart (if their URL scheme supports it)
- **Purchase history tracking** — log what you actually bought and at what price; compare to later prices to see if you timed it well
- **ML-based sale prediction** — with 6+ months of price history, train a simple model to predict when a given product will next go on sale
- **Cellar inventory integration** — integrate with Vivino or a simple local inventory to avoid buying things you already have in stock
- **Additional data sources** — The Wine Collective (RSS/scraper, wine-specific deals) and GroceryRun/Staticice (price comparison API, useful for cross-checking and dedup)

---

*Previous: [Phase 3 — Breadth](./PHASE_3.md) · Back to [README](./README.md)*
