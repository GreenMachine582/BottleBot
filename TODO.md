# 🔄 Migration TODO — adopting the shared `greentechhub-*` libraries

> This is a consolidated view for working *inside BottleBot*. The canonical source of truth for
> each item is the upstream repo's own migration tracking — tick things off here, but also reflect
> the change back there so the two don't drift apart:
> - [`greentechhub-fastapi/TODO.md`](../greentechhub-fastapi/TODO.md) — "🔄 Migration Tracking / BottleBot"
> - [`greentechhub-ui/TODO.md`](../greentechhub-ui/TODO.md) — "🔄 Migration Tracking / BottleBot"

## `greentechhub-ui` adoption

- [x] Drop custom `static/style.css` overrides in favor of the shared theme
- [x] Replace hand-rolled navbar with `gth-navbar`
- [ ] Migrate remaining components one at a time (done so far: `deal.html`'s metric tiles →
      `gth-stat-card`; dashboard's deals table + both its empty states → `gth-table`/`gth-table_body`/
      `gth-empty-state`; watchlist pagination, health tables, criteria tables — see below.
      Remaining: other cards)
  - [x] Watchlist pagination — `_watchlist_list.html`'s hand-rolled "load more" button →
        `gth_pagination` (`greentechhub_ui/components/pagination.html`). `watchlist.py`'s
        `_paginate()` offset-slicing logic is unchanged — only the rendering moved.
  - [ ] Other cards — spot-check `templates/deal.html` / `templates/dashboard.html` for any
        remaining non-migrated card markup
  - [x] Health tables — `_scrape_runs_table.html`, `_notification_log_table.html` →
        `gth_table` / `gth_table_body`
  - [x] Criteria tables — `templates/criteria.html` (scoring weights + category multipliers) →
        `gth_table` / `gth_table_body`

Not a gap — staying as-is: `.watchlist-pill` / `.watchlist-chip`, `.timeline`, and the
hot/watchlist/best-price row-highlight rules in `static/style.css` are genuinely BottleBot-specific
business styling, not theme duplication.

## `greentechhub-fastapi` adoption

- [ ] Swap hand-rolled `/health` and `/health/runs` (`src/web/routes/health.py`) for `register_health`
- [ ] Swap the ad-hoc `_paginate()` offset-slicing (`src/web/routes/watchlist.py:29-51`) for the
      `query` / `PageParams` adapter
- [ ] Adopt `register_auth`, if/when BottleBot grows a login (lowest priority — deferred upstream too)

## Packaging / deployment follow-up

- [ ] Once `greentechhub-ui` ships a pinned release, switch `requirements.txt` from
      `-e ../greentechhub-ui` to a pinned git-tag dependency (matching how `greentechhub-fastapi`
      and `greentechhub-ui` already pin `greentechhub-core`, e.g. `v0.6.0`), and drop the
      `GREENTECHHUB_UI_PATH` build-context plumbing in `Dockerfile` / `docker-compose.yml` /
      `.env.example`
