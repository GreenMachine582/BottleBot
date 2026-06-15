# Phase 2 — Intelligence: Score & Alert

> **Goal:** Turn raw price data into ranked deal scores and fire alerts via [apprise](https://github.com/caronc/apprise) — Discord is the primary channel, with ntfy and 100+ other services available through the same config — when something clears your configured threshold. Daily digest mode for less urgent deals.

**Status:** ✅ Complete

**Estimated effort:** 1–2 weekends
**Depends on:** Phase 1 (needs price history to calculate real discounts)
**Unlocks:** Phase 3 (more sources feed the same scoring pipeline)

---

## Deliverables

- [x] `criteria.yaml` schema + Pydantic config loader — [`config/criteria.yaml`](./config/criteria.yaml), [`src/scoring/criteria.py`](./src/scoring/criteria.py)
- [x] `.env`-based secrets via pydantic-settings (Discord webhook URL, ntfy URL) — [`src/config/settings.py`](./src/config/settings.py), [`.env.example`](./.env.example)
- [x] Deal scoring engine (weighted formula, 0–100 score) — [`src/scoring/engine.py`](./src/scoring/engine.py)
- [x] 90-day rolling average calculator (real discount vs retailer "was" price)
- [x] apprise-based notification module — Discord primary, ntfy as an additional target — [`src/alerts/notify.py`](./src/alerts/notify.py)
- [x] Alert messages link to both the retailer product page and the Phase 4 dashboard
- [x] Daily digest builder (sorted by score, top N deals) — [`src/alerts/digest.py`](./src/alerts/digest.py)
- [x] Immediate alert mode for high-score deals — [`src/run_scoring.py`](./src/run_scoring.py)
- [x] EOFY / Boxing Day / Easter sale calendar awareness — [`src/calendar.py`](./src/calendar.py)
- [x] Dry-run CLI (`python -m src.cli score`) using typer + rich — [`src/cli.py`](./src/cli.py)

---

## 1. Criteria config & secrets

[`config/criteria.yaml`](./config/criteria.yaml) holds all scoring/alert tuning — thresholds, weights, modifiers, category multipliers, and watchlist/brand block-allow lists. It's loaded and validated by [`src/scoring/criteria.py`](./src/scoring/criteria.py)'s `Criteria` Pydantic model (`load_criteria()`), so a typo or wrong type fails fast at startup rather than at scoring time. Ships with two example watchlist products and empty block/allow lists — edit to taste.

Webhook URLs are secrets and never go in `criteria.yaml`. [`src/config/settings.py`](./src/config/settings.py)'s `Settings` (pydantic-settings) loads `BOTTLEBOT_DISCORD_WEBHOOK_URL` and `BOTTLEBOT_NTFY_URL` from `.env` (see [`.env.example`](./.env.example)), in apprise's native URL format — `discord://<webhook_id>/<webhook_token>` and `ntfy://ntfy.sh/<topic>`. Adding another apprise target (Slack, email, Telegram, ...) is a new `Settings` field plus an `apobj.add(...)` call in `build_apprise()`.

---

## 2. Scoring engine

[`src/scoring/engine.py`](./src/scoring/engine.py) — `ScoringEngine.score_deal(rp, latest)` runs a deal through a filter pipeline, then a weighted scoring formula.

**Filters** (any failure returns `None` — the deal is skipped entirely):
- real discount vs `get_90d_average()` below `thresholds.min_discount_pct`
- absolute saving below `thresholds.min_saving_aud`
- brand on `brands.blocklist` (or not on a non-empty `brands.allowlist`)
- $/L (`cpl_aud`) above `thresholds.max_cpl_aud` for the product's category (or `default`)

**Score components** (each normalised to 0.0–1.0 before weighting):
- `discount_score` — real discount vs 90-day average, 60% = perfect
- `cpl_score` — $/L vs the `CATEGORY_AVG_CPL` benchmark for the category
- `bulk_score` — extra $ saved buying 12, $200 = perfect
- `cat_score` — your `categories` preference multiplier, normalised 0.5–1.5 → 0–1 (clamped to that range, so a multiplier below 0.5 can't push the score negative)

`base = (discount_score*w.real_discount_pct + cpl_score*w.cpl_rating + bulk_score*w.bulk_value + cat_score*w.category_pref) * 100`, then additive **modifiers** (capped at 100): `watchlist_bonus` if the product matches `watchlist.products`/`categories`, `new_low_bonus` if this is the all-time-lowest scraped price, `eofy_window_bonus` if `SaleCalendar` says today is in a sale window.

`score_all_current_deals()` scores every product with an `on_sale=True` price row, drops anything below `alerts.min_deal_score`, and returns the rest sorted by score descending.

---

## 3. Sale calendar

[`src/calendar.py`](./src/calendar.py) — `SaleCalendar.current_window(d)` checks four fixed-date windows (EOFY, Boxing Day, New Year, Click Frenzy) plus a moveable Easter window computed from `dateutil.easter.easter(year)` (4 days before Good Friday through 1 day after Easter Monday). `is_sale_window()` is `True` if `current_window()` returns anything.

---

## 4. Alerts: immediate + daily digest

[`src/alerts/notify.py`](./src/alerts/notify.py) — `build_apprise(settings)` assembles an `apprise.Apprise` object from `Settings`: Discord (tagged `immediate` + `digest`) and ntfy (tagged `digest`) if configured. `build_message(deal, base_url)` builds a markdown title/body — 🔥 if score ≥ 85 else 🍺, with discount/score/CPL/watchlist/new-low/bulk-saving lines, plus links to both the retailer product page and the Phase 4 dashboard (`{base_url}/deals/{retailer_product_id}`). `send_alert()` notifies with `tag="immediate"`.

[`src/alerts/digest.py`](./src/alerts/digest.py) — `send_digest()` takes the top `alerts.digest_max_deals` scored deals and sends them as one markdown message tagged `digest`. No-ops if there are no deals.

[`src/run_scoring.py`](./src/run_scoring.py) — `run_scoring()` scores all current deals, splits them at `alerts.immediate_threshold`, and immediately alerts on the high scorers (0.5s sleep between sends to respect rate limits). The rest wait for the next digest.

---

## 5. Scheduling & CLI

[`src/scheduler.py`](./src/scheduler.py) adds two jobs alongside Phase 1's scrape job: `run_scoring` on the same 6-hour interval, offset 5 minutes after the scrape (via `next_run_time`) so it always runs against freshly scraped data; and `run_digest` as a daily cron job at `criteria.alerts.digest_time` (the scheduler runs in `Australia/Sydney`, so this is AEST/AEDT).

[`src/cli.py`](./src/cli.py)'s `score` command runs `score_all_current_deals()` and prints a ranked Rich table (`python -m src.cli score --top 20`) — no alerts are sent, useful for tuning `criteria.yaml`.

---

## 6. Docker

[`.dockerignore`](./.dockerignore) keeps `.env`, `.venv`, caches and `*.db` out of the build context. [`docker-compose.yml`](./docker-compose.yml) passes `BOTTLEBOT_DISCORD_WEBHOOK_URL`/`BOTTLEBOT_NTFY_URL` through via `${VAR:-}` substitution from a root `.env` — `docker compose up` still starts cleanly with no `.env` present (alerts just won't fire).

---

## 7. Testing

[`tests/test_calendar.py`](./tests/test_calendar.py), [`tests/test_scoring.py`](./tests/test_scoring.py) and [`tests/test_notify.py`](./tests/test_notify.py) cover the sale calendar windows (including a self-computing Easter check via `dateutil`), the scoring filter pipeline and bonus modifiers (watchlist, new-low, EOFY window), `score_all_current_deals` ranking/filtering, and alert/digest message formatting — all against in-memory SQLite, matching Phase 1's fixture style.

---

## Phase 2 acceptance criteria

- [x] Scoring engine returns ranked deals from the DB
- [x] Deals below `min_discount_pct` or `min_saving_aud` are filtered
- [x] Blocklisted brands are excluded
- [x] Watchlist items receive bonus score and appear at top
- [x] Immediate alerts fire for scores ≥ `immediate_threshold`
- [x] Discord message built with correct fields and a working "View on BottleBot" link
- [x] `.env` secrets load correctly via `Settings` and are never written to `criteria.yaml`
- [x] Daily digest scheduled correctly and sends at configured time
- [x] `python -m src.cli score` prints a ranked table without sending any alert
- [x] EOFY window modifier applies correctly in June
- [x] Easter window is computed correctly for the given year via `dateutil.easter.easter`

---

## Known gotchas

- **`avg`/`all_time_low` truthiness:** `get_90d_average`/`get_all_time_low` return `float(result) if result is not None else None` — a genuine `$0` price would be falsy but is not "no data". Don't change this back to a bare truthiness check.
- **`cat_score` is clamped to 0–1:** a `categories` multiplier below 0.5 in `criteria.yaml` would otherwise produce a negative score component and quietly drag the whole deal score down.
- **EOFY/Easter modifiers depend on "today":** scoring tests either zero `eofy_window_bonus` or monkeypatch `ScoringEngine._in_sale_window` for determinism. The Easter window test computes its expected dates from `dateutil.easter.easter(year)` rather than hardcoding a date, since Easter moves every year.
- **Discord webhook URL format:** apprise expects `discord://<webhook_id>/<webhook_token>` — the two path segments at the end of the webhook URL Discord gives you, not the full URL.
- **Two different `.env` mechanisms:** pydantic-settings (`env_file=".env"`, read by the running process) and Docker Compose's `${VAR:-}` substitution (reads a root `.env` for `docker-compose.yml` itself) both point at the same file here, but are separate features. Avoid `env_file:` in `docker-compose.yml`'s `services:` block for these — Compose hard-fails if the file doesn't exist, breaking `docker compose up` for anyone without a local `.env`.
- **OneDrive + `.venv`:** this project lives under OneDrive, and `.venv` has disappeared mid-session more than once (sync churn on thousands of small files). If `pytest`/`ruff` suddenly report missing modules, recreate it: `python -m venv .venv && .venv/Scripts/pip install -r requirements.txt`.

---

*Previous: [Phase 1 — Foundation](./PHASE_1.md) · Next: [Phase 3 — Breadth](./PHASE_3.md)*
