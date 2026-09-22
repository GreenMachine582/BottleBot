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
        offset-slicing logic has since moved to page/size — see `greentechhub-fastapi` adoption
        below.
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

- [x] Swap hand-rolled `/health` and `/health/runs` for `register_health` — done 2026-09-22: the
      old dashboard (scrape runs, notifications, timeline) moved to `/activity` and
      `/activity/runs` (`src/web/routes/activity.py`), since `register_health`'s `/health`/
      `/health/ready` paths aren't configurable and would have collided. `/health/ready` runs a
      DB check (`check_bottlebot_db`) against BottleBot's sync SQLAlchemy engine via
      `asyncio.to_thread`, since `greentechhub-core`'s `check_database` expects an async-shaped
      engine.
- [x] Swap the ad-hoc `_paginate()` offset-slicing for the `query` / `PageParams` adapter — done
      2026-09-22: `/watchlist/list` now takes `PageParams` (`page`/`size`, validated `ge=1`/
      `1-100`) instead of an unvalidated `offset`. Only the `page`/`size` half of the adapter
      applies — `sort`/`filter`/`to_page_request()` are unused, since BottleBot filters/groups
      `Product` rows into `ProductGroup`s in Python before pagination, not against a
      directly-queryable source those could resolve against. Neither `Page` nor `PageParams` has
      any concept of a `next_url`, so `watchlist.py` still builds that by hand for `gth_pagination`
      (`_slice_page`/`_next_url`) — the glue BottleBot needed didn't get any smaller, just
      switched units from offset to page/size. `WATCHLIST_PAGE_SIZE` stays the default page size
      via a small `_watchlist_page_params` dependency (reads it at call time, not baked into a
      `Query(...)` default, so it stays test-monkeypatchable).
- [ ] Adopt `register_auth`, if/when BottleBot grows a login (lowest priority — deferred upstream too)

## Packaging / deployment follow-up

- [ ] Once `greentechhub-ui` ships a pinned release, switch `requirements.txt` from
      `-e ../greentechhub-ui` to a pinned git-tag dependency (matching how `greentechhub-fastapi`
      and `greentechhub-ui` already pin `greentechhub-core`, e.g. `v0.6.0`), and drop the
      `GREENTECHHUB_UI_PATH` build-context plumbing in `Dockerfile` / `docker-compose.yml` /
      `.env.example`
