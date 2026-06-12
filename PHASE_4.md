# Phase 4 — UX: Dashboard & Tools

> **Goal:** A simple self-hosted web UI to browse current deals, manage your watchlist and criteria, view price history charts, and run the bulk-buy calculator. FastAPI backend with htmx-powered frontend — no JavaScript framework required.

**Estimated effort:** 2–3 weekends  
**Depends on:** Phases 1–3 (all data, scoring, and sources must be running)  
**Access:** Local network via Tailscale, or Pi's LAN IP. Not exposed to the public internet.

---

## Deliverables

- [ ] FastAPI app with Jinja2 templates
- [ ] Dashboard: today's top deals, sorted by score
- [ ] Deal detail page: price history chart, cross-retailer comparison, bulk-buy calc
- [ ] Watchlist manager: add/remove products and categories via UI
- [ ] Criteria editor: adjust weights and thresholds without editing YAML by hand
- [ ] Price history chart (Plotly, inline SVG or PNG)
- [ ] Bulk-buy calculator widget
- [ ] EOFY/sale calendar indicator in header
- [ ] Scrape run status / health panel
- [ ] Tailscale-accessible, Docker-networked

---

## 1. App structure

```
bottlebot/web/
├── app.py              # FastAPI app + router registration
├── routes/
│   ├── dashboard.py    # GET / — top deals today
│   ├── deals.py        # GET /deals/{id} — deal detail + chart
│   ├── watchlist.py    # GET/POST /watchlist
│   ├── criteria.py     # GET/POST /criteria — edit config via UI
│   └── health.py       # GET /health — scrape run status
├── templates/
│   ├── base.html       # Shared layout, nav
│   ├── dashboard.html
│   ├── deal.html
│   ├── watchlist.html
│   ├── criteria.html
│   └── health.html
└── static/
    └── style.css       # Minimal custom styles (mostly Pico CSS)
```

---

## 2. FastAPI app

```python
# bottlebot/web/app.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .routes import dashboard, deals, watchlist, criteria, health

app = FastAPI(title="BottleBot", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="bottlebot/web/static"), name="static")
templates = Jinja2Templates(directory="bottlebot/web/templates")

app.include_router(dashboard.router)
app.include_router(deals.router)
app.include_router(watchlist.router)
app.include_router(criteria.router)
app.include_router(health.router)
```

Run with: `uvicorn bottlebot.web.app:app --host 0.0.0.0 --port 8080`

---

## 3. Dashboard route

```python
# bottlebot/web/routes/dashboard.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ...db.models import engine
from ...scoring.engine import ScoringEngine
from ...scoring.criteria import load_criteria
from ...calendar import SaleCalendar

router = APIRouter()
templates = Jinja2Templates(directory="bottlebot/web/templates")

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    criteria = load_criteria()
    with Session(engine) as session:
        scorer = ScoringEngine(session, criteria)
        deals = scorer.score_all_current_deals()

    sale_window = SaleCalendar().current_window()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "deals": deals[:50],
        "sale_window": sale_window,
        "min_score": criteria.alerts.min_deal_score,
    })
```

---

## 4. Dashboard template

```html
<!-- bottlebot/web/templates/dashboard.html -->
{% extends "base.html" %}
{% block content %}

{% if sale_window %}
<div class="sale-banner">
  🔥 {{ sale_window }} sale window active — thresholds adjusted
</div>
{% endif %}

<h2>Today's deals <small>{{ deals|length }} above score {{ min_score }}</small></h2>

<table>
  <thead>
    <tr>
      <th>Score</th>
      <th>Product</th>
      <th>Price</th>
      <th>Real disc.</th>
      <th>$/L</th>
      <th>Retailer</th>
      <th>Buy 12</th>
    </tr>
  </thead>
  <tbody>
  {% for deal in deals %}
    <tr class="{{ 'hot' if deal.score >= 85 else '' }} {{ 'watchlist' if deal.is_watchlist else '' }}">
      <td>
        <strong>{{ deal.score }}</strong>
        {% if deal.is_new_low %}<span title="All-time low">📉</span>{% endif %}
        {% if deal.is_watchlist %}<span title="Watchlist">⭐</span>{% endif %}
      </td>
      <td><a href="/deals/{{ deal.retailer_product_id }}">{{ deal.product_name }}</a></td>
      <td>${{ "%.2f"|format(deal.current_price) }}</td>
      <td>{{ "%.0f"|format(deal.real_discount_pct) }}%</td>
      <td>{% if deal.cpl_aud %}${{ "%.2f"|format(deal.cpl_aud) }}{% else %}—{% endif %}</td>
      <td>{{ deal.retailer }}</td>
      <td>{% if deal.bulk_saving_12 %}save ${{ "%.0f"|format(deal.bulk_saving_12) }}{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

{% endblock %}
```

---

## 5. Deal detail page

The deal detail page shows:
- Full score breakdown
- Price history chart (90 days)
- Cross-retailer price comparison
- Bulk-buy calculator

```python
# bottlebot/web/routes/deals.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ...db.models import engine, RetailerProduct, PriceHistory
from ...scoring.cross_retailer import compare_product_across_retailers
import plotly.graph_objects as go
import plotly.io as pio

router = APIRouter()
templates = Jinja2Templates(directory="bottlebot/web/templates")

def build_price_chart(history: list[PriceHistory]) -> str:
    """Returns an HTML div containing the Plotly chart."""
    dates = [h.scraped_at for h in history]
    prices = [h.price_aud for h in history]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=prices,
        mode="lines+markers",
        name="Price",
        line=dict(color="#5BCAA5", width=2),
        marker=dict(size=4),
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=220,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)", tickprefix="$"),
        font=dict(family="system-ui", size=12),
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False, div_id="price-chart")

@router.get("/deals/{retailer_product_id}", response_class=HTMLResponse)
async def deal_detail(request: Request, retailer_product_id: int):
    with Session(engine) as session:
        rp = session.get(RetailerProduct, retailer_product_id)
        if not rp:
            return HTMLResponse("Not found", status_code=404)

        history = (
            session.query(PriceHistory)
            .filter_by(retailer_product_id=retailer_product_id)
            .order_by(PriceHistory.scraped_at)
            .all()
        )
        cross = compare_product_across_retailers(session, rp.product_id)
        chart_html = build_price_chart(history) if history else None

    return templates.TemplateResponse("deal.html", {
        "request": request,
        "rp": rp,
        "product": rp.product,
        "latest": history[-1] if history else None,
        "history": history,
        "chart_html": chart_html,
        "cross": cross,
    })
```

---

## 6. Bulk-buy calculator

Displayed on the deal detail page. Pure Jinja template — no JS needed for basic version.

```html
<!-- Snippet for deal.html -->
{% if latest %}
<section class="bulk-calc">
  <h3>Bulk-buy calculator</h3>
  <table>
    <thead>
      <tr><th>Qty</th><th>Total cost</th><th>Saving vs avg</th><th>$/bottle</th></tr>
    </thead>
    <tbody>
    {% set price = latest.price_aud %}
    {% set avg = avg_90d %}
    {% for qty in [1, 6, 12, 24] %}
      <tr {% if qty == 12 %}class="highlight"{% endif %}>
        <td>{{ qty }}</td>
        <td>${{ "%.2f"|format(price * qty) }}</td>
        <td>${{ "%.2f"|format((avg - price) * qty) }}</td>
        <td>${{ "%.2f"|format(price) }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <p class="hint">Row highlighted at 12 — typical bulk-buy threshold for free delivery.</p>
</section>
{% endif %}
```

For a live interactive version (quantity slider), add an htmx `hx-get` endpoint that recalculates and returns just the table fragment:

```python
@router.get("/deals/{id}/bulkcalc", response_class=HTMLResponse)
async def bulk_calc(id: int, qty: int = 12):
    # Returns just the <table> fragment for htmx swap
    ...
```

```html
<input type="range" min="1" max="48" value="12"
  hx-get="/deals/{{ rp.id }}/bulkcalc"
  hx-trigger="input"
  hx-target="#bulk-table"
  hx-include="this"
  name="qty">
<div id="bulk-table">...</div>
```

---

## 7. Watchlist manager

```python
# bottlebot/web/routes/watchlist.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from ...scoring.criteria import load_criteria
import yaml

router = APIRouter()
templates = Jinja2Templates(directory="bottlebot/web/templates")

CRITERIA_PATH = "config/criteria.yaml"

@router.get("/watchlist", response_class=HTMLResponse)
async def get_watchlist(request: Request):
    criteria = load_criteria(CRITERIA_PATH)
    return templates.TemplateResponse("watchlist.html", {
        "request": request,
        "products": criteria.watchlist.products,
        "categories": criteria.watchlist.categories,
    })

@router.post("/watchlist/add")
async def add_to_watchlist(
    request: Request,
    product_name: str = Form(None),
    category: str = Form(None),
):
    with open(CRITERIA_PATH) as f:
        raw = yaml.safe_load(f)

    if product_name:
        raw.setdefault("watchlist", {}).setdefault("products", [])
        if product_name not in raw["watchlist"]["products"]:
            raw["watchlist"]["products"].append(product_name)

    if category:
        raw.setdefault("watchlist", {}).setdefault("categories", [])
        if category not in raw["watchlist"]["categories"]:
            raw["watchlist"]["categories"].append(category)

    with open(CRITERIA_PATH, "w") as f:
        yaml.dump(raw, f, default_flow_style=False)

    return RedirectResponse("/watchlist", status_code=303)

@router.post("/watchlist/remove")
async def remove_from_watchlist(
    request: Request,
    product_name: str = Form(None),
    category: str = Form(None),
):
    with open(CRITERIA_PATH) as f:
        raw = yaml.safe_load(f)

    if product_name and product_name in raw.get("watchlist", {}).get("products", []):
        raw["watchlist"]["products"].remove(product_name)

    if category and category in raw.get("watchlist", {}).get("categories", []):
        raw["watchlist"]["categories"].remove(category)

    with open(CRITERIA_PATH, "w") as f:
        yaml.dump(raw, f, default_flow_style=False)

    return RedirectResponse("/watchlist", status_code=303)
```

---

## 8. Health / scrape status panel

```python
# bottlebot/web/routes/health.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ...db.models import engine, ScrapeRun

router = APIRouter()
templates = Jinja2Templates(directory="bottlebot/web/templates")

@router.get("/health", response_class=HTMLResponse)
async def health(request: Request):
    with Session(engine) as session:
        recent_runs = (
            session.query(ScrapeRun)
            .order_by(ScrapeRun.started_at.desc())
            .limit(30)
            .all()
        )
    return templates.TemplateResponse("health.html", {
        "request": request,
        "runs": recent_runs,
    })
```

The health page shows a table of recent scrape runs: source, start time, duration, products seen, prices inserted, and status (green tick / red cross). Provides instant visibility into which scrapers are working and which have gone stale.

---

## 9. Base template

Uses [Pico CSS](https://picocss.com/) — classless, semantic HTML, dark mode out of the box. No JS framework.

```html
<!-- bottlebot/web/templates/base.html -->
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BottleBot {% block title %}{% endblock %}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <script src="https://unpkg.com/htmx.org@1.9.10/dist/htmx.min.js"></script>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="container">
    <nav>
      <ul><li><strong>🍺 BottleBot</strong></li></ul>
      <ul>
        <li><a href="/">Deals</a></li>
        <li><a href="/watchlist">Watchlist</a></li>
        <li><a href="/criteria">Criteria</a></li>
        <li><a href="/health">Health</a></li>
      </ul>
    </nav>
  </header>
  <main class="container">
    {% block content %}{% endblock %}
  </main>
  <footer class="container">
    <small>BottleBot · Self-hosted · Data updates every 6h</small>
  </footer>
</body>
</html>
```

---

## 10. Docker Compose update

```yaml
# docker-compose.yml (Phase 4 update)
services:
  bottlebot:
    build: .
    container_name: bottlebot-scraper
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    environment:
      - DB_PATH=/app/data/bottlebot.db
      - TZ=Australia/Sydney
    command: python -m bottlebot.scheduler

  bottlebot-web:
    build: .
    container_name: bottlebot-web
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    ports:
      - "8080:8080"
    environment:
      - DB_PATH=/app/data/bottlebot.db
      - TZ=Australia/Sydney
    command: uvicorn bottlebot.web.app:app --host 0.0.0.0 --port 8080
    depends_on:
      - bottlebot
```

Access via `http://<pi-ip>:8080` on LAN, or `http://bottlebot` via Tailscale if you've set up the subnet router.

---

## 11. Ansible deploy task

```yaml
# ansible/bottlebot.yml (Phase 4 additions)
- name: Deploy BottleBot web UI
  hosts: homelab
  tasks:
    - name: Ensure bottlebot directory exists
      file:
        path: /opt/bottlebot
        state: directory

    - name: Copy docker-compose.yml
      copy:
        src: docker-compose.yml
        dest: /opt/bottlebot/docker-compose.yml

    - name: Pull and restart containers
      community.docker.docker_compose_v2:
        project_src: /opt/bottlebot
        pull: always
        state: present

    - name: Open port 8080 in UFW (LAN only)
      ufw:
        rule: allow
        port: 8080
        src: "192.168.0.0/16"
```

---

## Phase 4 acceptance criteria

- [ ] `docker compose up` starts both scraper and web containers cleanly
- [ ] Dashboard loads at `http://pi-ip:8080` and shows ranked deals
- [ ] Deal detail page shows price history chart for a product with 7+ days of data
- [ ] Cross-retailer comparison section shows prices from at least 2 retailers on matched products
- [ ] Bulk-buy table calculates correctly for qty 1, 6, 12, 24
- [ ] Watchlist add/remove persists to `criteria.yaml` and immediately affects next score run
- [ ] Health page shows last 30 scrape runs with status
- [ ] EOFY banner appears in header during June 15–30
- [ ] Accessible via Tailscale from phone

---

## Potential Phase 5 ideas (future)

- **Price alerts via iOS/Android push** — ntfy app already handles this; Phase 5 would add rich notifications with product image
- **Automated cart builder** — given a scored deal list, generate a shareable link to a Dan Murphy's cart (if their URL scheme supports it)
- **Purchase history tracking** — log what you actually bought and at what price; compare to later prices to see if you timed it well
- **ML-based sale prediction** — with 6+ months of price history, train a simple model to predict when a given product will next go on sale
- **Cellar inventory integration** — integrate with Vivino or a simple local inventory to avoid buying things you already have in stock

---

*Previous: [Phase 3 — Breadth](./PHASE_3.md) · Back to [README](./README.md)*
