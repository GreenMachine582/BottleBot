"""Smoke tests for Phase 4 web routes.

Each route is exercised against a real in-memory SQLite database so we
confirm templates render without errors and all routes respond correctly.
The engine in each route module is patched to point at the temp DB.
"""
import yaml
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, ScrapeRun
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
    import src.web.routes.health as health_mod
    import src.web.routes.watchlist as watchlist_mod
    import src.web.routes.criteria as criteria_mod

    for mod in [dash_mod, deals_mod, health_mod]:
        mod.engine = test_engine
    watchlist_mod.CRITERIA_PATH = criteria_path
    criteria_mod.CRITERIA_PATH = criteria_path

    # Seed a ScrapeRun so the health page has something to show
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
        session.commit()

    yield TestClient(app)


def test_dashboard_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Today's deals" in resp.text


def test_dashboard_shows_empty_state(client):
    resp = client.get("/")
    assert "No deals above score" in resp.text or "Today's deals" in resp.text


def test_health_loads_and_shows_run(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "danmurphys" in resp.text
    assert "success" in resp.text


def test_watchlist_loads(client):
    resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert "Watchlist" in resp.text


def test_watchlist_add_and_remove(client):
    resp = client.post("/watchlist/add", data={"product_name": "Penfolds Bin 389"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "Penfolds Bin 389" in resp.text

    resp = client.post("/watchlist/remove", data={"product_name": "Penfolds Bin 389"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "Penfolds Bin 389" not in resp.text


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
