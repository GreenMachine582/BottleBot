"""Smoke tests for Phase 4 web routes.

Each route is exercised against a real in-memory SQLite database so we
confirm templates render without errors and all routes respond correctly.
The engine in each route module is patched to point at the temp DB.
"""
import json
import re
from datetime import datetime, timedelta

import yaml
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, Product, ScrapeRun
from src.web.app import app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web_test")

    # Real temp DB so routes can query it
    test_engine = create_engine("sqlite:///" + str(tmp / "test.db"))
    Base.metadata.create_all(test_engine)

    # Minimal criteria.yaml so load_criteria() doesn't fail
    config_dir = tmp / "config"
    config_dir.mkdir()
    criteria_path = str(config_dir / "criteria.yaml")
    (config_dir / "criteria.yaml").write_text(yaml.dump({
        "alerts": {
            "min_deal_score": 65,
            "immediate_threshold": 85,
            "digest_time": "08:00",
            "digest_max_deals": 10,
        },
        "web": {"base_url": "http://testserver"},
        "scoring": {
            "weights": {
                "real_discount_pct": 0.35,
                "cpl_rating": 0.30,
                "bulk_value": 0.20,
                "category_pref": 0.15,
            },
            "modifiers": {
                "watchlist_bonus": 20,
                "eofy_window_bonus": 10,
                "new_low_bonus": 15,
            },
        },
        "categories": {},
        "thresholds": {
            "min_discount_pct": 20,
            "min_saving_aud": 10,
            "max_cpl_aud": {"default": 30},
        },
        "watchlist": {"products": [], "categories": []},
        "brands": {"blocklist": [], "allowlist": []},
    }))

    # Redirect all route modules to the test engine and temp criteria path
    import src.web.routes.dashboard as dash_mod
    import src.web.routes.deals as deals_mod
    import src.web.routes.activity as activity_mod
    import src.web.routes.watchlist as watchlist_mod
    import src.web.routes.criteria as criteria_mod
    import src.web.routes.scrape as scrape_mod

    for mod in [dash_mod, deals_mod, activity_mod, watchlist_mod, scrape_mod]:
        mod.engine = test_engine
    watchlist_mod.CRITERIA_PATH = criteria_path
    criteria_mod.CRITERIA_PATH = criteria_path

    # Seed a ScrapeRun so the health page has something to show, plus a
    # multi-volume product so the watchlist page has something to toggle.
    from datetime import datetime, timedelta
    with Session(test_engine) as session:
        session.add(ScrapeRun(
            source="danmurphys",
            started_at=datetime.utcnow() - timedelta(minutes=5),
            finished_at=datetime.utcnow(),
            status="success",
            products_seen=42,
            prices_inserted=7,
        ))
        session.add_all([
            Product(name="Penfolds Bin 389 750mL", brand="Penfolds", category="wine_red", volume_ml=750),
            Product(name="Penfolds Bin 389 1L", brand="Penfolds", category="wine_red", volume_ml=1000),
        ])
        session.commit()

    yield TestClient(app)


def test_dashboard_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Today's deals" in resp.text


def test_dashboard_shows_empty_state(client):
    resp = client.get("/")
    assert "No deals above score" in resp.text or "Today's deals" in resp.text


def test_activity_loads_and_shows_run(client):
    resp = client.get("/activity")
    assert resp.status_code == 200
    assert "danmurphys" in resp.text
    assert "success" in resp.text


def test_liveness_returns_healthy(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_readiness_returns_healthy_when_db_reachable(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["checks"][0]["status"] == "healthy"


def test_readiness_returns_503_when_db_unreachable(client, monkeypatch):
    import src.web.routes.activity as activity_mod

    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(activity_mod, "engine", _BrokenEngine())

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["checks"][0]["status"] == "unhealthy"


def test_scrape_trigger_unknown_source_404(client):
    resp = client.post("/scrape/trigger/not-a-real-source")
    assert resp.status_code == 404


def test_scrape_trigger_running_returns_409_with_toast(client, monkeypatch, tmp_path):
    import src.web.routes.scrape as scrape_mod

    trig_engine = create_engine("sqlite:///" + str(tmp_path / "trigger_running.db"))
    Base.metadata.create_all(trig_engine)
    with Session(trig_engine) as s:
        s.add(ScrapeRun(source="bws", started_at=datetime.utcnow(), status="running"))
        s.commit()

    monkeypatch.setattr(scrape_mod, "engine", trig_engine)

    resp = client.post("/scrape/trigger/bws")
    assert resp.status_code == 409
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert toast["kind"] == "warning"
    assert toast["message"] == "bws is already running"


def test_scrape_trigger_cooldown_returns_409_with_toast(client, monkeypatch, tmp_path):
    import src.web.routes.scrape as scrape_mod

    trig_engine = create_engine("sqlite:///" + str(tmp_path / "trigger_cooldown.db"))
    Base.metadata.create_all(trig_engine)
    with Session(trig_engine) as s:
        s.add(ScrapeRun(
            source="danmurphys",
            started_at=datetime.utcnow() - timedelta(minutes=2),
            finished_at=datetime.utcnow() - timedelta(minutes=1),
            status="success",
        ))
        s.commit()

    monkeypatch.setattr(scrape_mod, "engine", trig_engine)

    resp = client.post("/scrape/trigger/danmurphys")
    assert resp.status_code == 409
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert toast["kind"] == "warning"
    assert "cooldown" in toast["message"]
    assert "4m remaining" in toast["message"]


def test_scrape_trigger_success_returns_204_with_toast(client, monkeypatch, tmp_path):
    import src.web.routes.scrape as scrape_mod

    trig_engine = create_engine("sqlite:///" + str(tmp_path / "trigger_success.db"))
    Base.metadata.create_all(trig_engine)

    monkeypatch.setattr(scrape_mod, "engine", trig_engine)
    monkeypatch.setattr(scrape_mod, "_run_source", lambda source: None)

    resp = client.post("/scrape/trigger/firstchoice")
    assert resp.status_code == 204
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert toast["kind"] == "success"
    assert toast["message"] == "Scraper queued for firstchoice"


def test_scrape_trigger_all_when_all_busy_returns_409(client, monkeypatch, tmp_path):
    import src.web.routes.scrape as scrape_mod

    trig_engine = create_engine("sqlite:///" + str(tmp_path / "trigger_all_busy.db"))
    Base.metadata.create_all(trig_engine)
    with Session(trig_engine) as s:
        for source in scrape_mod._SCRAPERS:
            s.add(ScrapeRun(source=source, started_at=datetime.utcnow(), status="running"))
        s.commit()

    monkeypatch.setattr(scrape_mod, "engine", trig_engine)

    resp = client.post("/scrape/trigger")
    assert resp.status_code == 409
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert toast["kind"] == "warning"
    assert toast["message"] == "All scrapers busy or on cooldown"


def test_scrape_trigger_all_queues_available_sources(client, monkeypatch, tmp_path):
    import src.web.routes.scrape as scrape_mod

    trig_engine = create_engine("sqlite:///" + str(tmp_path / "trigger_all_mixed.db"))
    Base.metadata.create_all(trig_engine)
    with Session(trig_engine) as s:
        s.add(ScrapeRun(source="danmurphys", started_at=datetime.utcnow(), status="running"))
        s.commit()

    monkeypatch.setattr(scrape_mod, "engine", trig_engine)
    monkeypatch.setattr(scrape_mod, "_run_source", lambda source: None)

    resp = client.post("/scrape/trigger")
    assert resp.status_code == 204
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert toast["kind"] == "success"
    assert "Queued:" in toast["message"]
    assert "Skipped 1" in toast["message"]


def test_watchlist_loads(client):
    resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert "Watchlist" in resp.text
    assert "Penfolds Bin 389" in resp.text


def test_watchlist_toggle_category(client):
    resp = client.post("/watchlist/toggle-category", data={"category": "whisky"})
    assert resp.status_code == 200
    assert "btn-success" in resp.text
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert "added to watchlist" in toast["message"]
    assert toast["kind"] == "success"

    resp = client.post("/watchlist/toggle-category", data={"category": "whisky"})
    assert resp.status_code == 200
    assert "btn-success" not in resp.text
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert "removed from watchlist" in toast["message"]


def test_watchlist_toggle_category_rejects_unknown_category(client):
    resp = client.post("/watchlist/toggle-category", data={"category": "not-a-real-category"})
    assert resp.status_code == 404


def test_watchlist_toggle_volume(client):
    resp = client.get("/watchlist")
    assert resp.status_code == 200
    match = re.search(r'"product_id":\s*(\d+)', resp.text)
    assert match, "expected at least one volume chip with a product_id"
    product_id = int(match.group(1))

    resp = client.post("/watchlist/toggle-volume", data={"product_id": product_id})
    assert resp.status_code == 200
    assert "btn-success" in resp.text
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert "added to watchlist" in toast["message"]
    assert toast["kind"] == "success"

    resp = client.post("/watchlist/toggle-volume", data={"product_id": product_id})
    assert resp.status_code == 200
    assert "btn-success" not in resp.text
    toast = json.loads(resp.headers["hx-trigger"])["showToast"]
    assert "removed from watchlist" in toast["message"]


def test_watchlist_toggle_volume_unknown_id_returns_404(client):
    resp = client.post("/watchlist/toggle-volume", data={"product_id": 999999})
    assert resp.status_code == 404


def test_watchlist_list_filters_by_query(client):
    resp = client.get("/watchlist/list", params={"q": "Penfolds"})
    assert resp.status_code == 200
    assert "Penfolds Bin 389" in resp.text

    resp = client.get("/watchlist/list", params={"q": "Nonexistent Product XYZ"})
    assert resp.status_code == 200
    assert "No products match" in resp.text


def test_watchlist_list_paginates(client, monkeypatch, tmp_path):
    """Self-contained: swaps in its own tiny engine + page size via
    monkeypatch (auto-reverted after the test) rather than depending on the
    shared module-scoped fixture's product count or test ordering. Uses a
    file-based DB, not :memory:, since each request opens a new connection
    and sqlite's :memory: DB is connection-scoped (a fresh one per connection)."""
    import src.web.routes.watchlist as watchlist_mod

    pag_engine = create_engine("sqlite:///" + str(tmp_path / "pagination_test.db"))
    Base.metadata.create_all(pag_engine)
    with Session(pag_engine) as s:
        s.add_all([
            Product(name="Aaa Whisky 700mL", brand="Aaa", category="whisky", volume_ml=700),
            Product(name="Zzz Vodka 700mL", brand="Zzz", category="vodka", volume_ml=700),
        ])
        s.commit()

    monkeypatch.setattr(watchlist_mod, "engine", pag_engine)
    monkeypatch.setattr(watchlist_mod, "WATCHLIST_PAGE_SIZE", 1)

    resp = client.get("/watchlist/list")
    assert resp.status_code == 200
    assert "Aaa Whisky" in resp.text
    assert "Zzz Vodka" not in resp.text
    match = re.search(r'hx-get="(/watchlist/list\?page=2&amp;size=1[^"]*)"', resp.text)
    assert match, "expected a Load more button pointing at page=2&size=1"

    resp2 = client.get(match.group(1).replace("&amp;", "&"))
    assert resp2.status_code == 200
    assert "Zzz Vodka" in resp2.text
    assert "Load more" not in resp2.text


def test_watchlist_list_rejects_invalid_page(client):
    resp = client.get("/watchlist/list", params={"page": 0})
    assert resp.status_code == 422

    resp = client.get("/watchlist/list", params={"size": 101})
    assert resp.status_code == 422


def test_criteria_loads(client):
    resp = client.get("/criteria")
    assert resp.status_code == 200
    assert "Min deal score" in resp.text


def test_criteria_save_valid_values(client):
    resp = client.post("/criteria", data={
        "min_deal_score": "60",
        "immediate_threshold": "80",
        "min_discount_pct": "15",
        "min_saving_aud": "8",
    }, follow_redirects=True)
    assert resp.status_code == 200


def test_deal_detail_returns_404_for_unknown_id(client):
    resp = client.get("/deals/99999")
    assert resp.status_code == 404


def test_bulk_calc_returns_404_for_unknown_id(client):
    resp = client.get("/deals/99999/bulkcalc?qty=6")
    assert resp.status_code == 404
