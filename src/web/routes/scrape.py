from datetime import datetime, timedelta

import greentechhub_ui
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ...config.settings import Settings
from ...db.engine import engine
from ...db.models import ScrapeRun
from ...scrapers.bws import BWSScraper
from ...scrapers.cellarmasters import CellarMastersScraper
from ...scrapers.danmurphys import DanMurphysScraper
from ...scrapers.firstchoice import FirstChoiceScraper
from ...scrapers.liquorland import LiquorlandScraper
from ...scrapers.vintagecellars import VintageCellarsScraper

router = APIRouter()

_SCRAPERS = {
    "danmurphys": DanMurphysScraper,
    "bws": BWSScraper,
    "liquorland": LiquorlandScraper,
    "firstchoice": FirstChoiceScraper,
    "cellarmasters": CellarMastersScraper,
    "vintagecellars": VintageCellarsScraper,
}


def _check_can_run(source: str, cooldown_minutes: int) -> tuple[bool, str]:
    """
    Returns (ok, reason). Blocks if the source is currently running or finished
    within the cooldown window.
    """
    with Session(engine) as session:
        running = (
            session.query(ScrapeRun)
            .filter_by(source=source, status="running")
            .first()
        )
        if running:
            return False, f"{source} is already running"

        if cooldown_minutes > 0:
            cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
            recent = (
                session.query(ScrapeRun)
                .filter(
                    ScrapeRun.source == source,
                    ScrapeRun.finished_at >= cutoff,
                )
                .order_by(ScrapeRun.finished_at.desc())
                .first()
            )
            if recent:
                elapsed = int((datetime.utcnow() - recent.finished_at).total_seconds() / 60)
                remaining = cooldown_minutes - elapsed
                return False, f"{source} on cooldown — {remaining}m remaining"

    return True, ""


def _run_source(source: str) -> None:
    from ...scheduler import run_scraper
    run_scraper(_SCRAPERS[source], source)


@router.post("/scrape/trigger/{source}")
async def trigger_scrape(source: str, background_tasks: BackgroundTasks):
    if source not in _SCRAPERS:
        return HTMLResponse("", status_code=404)

    settings = Settings()
    ok, reason = _check_can_run(source, settings.scrape_cooldown_minutes)
    if not ok:
        resp = HTMLResponse("", status_code=409)
        resp.headers["HX-Trigger"] = greentechhub_ui.toast(reason, "warning")
        return resp

    background_tasks.add_task(_run_source, source)
    resp = HTMLResponse("", status_code=204)
    resp.headers["HX-Trigger"] = greentechhub_ui.toast(f"Scraper queued for {source}")
    return resp


@router.post("/scrape/trigger")
async def trigger_all(background_tasks: BackgroundTasks):
    settings = Settings()
    queued = []
    skipped = []

    for source in _SCRAPERS:
        ok, reason = _check_can_run(source, settings.scrape_cooldown_minutes)
        if ok:
            background_tasks.add_task(_run_source, source)
            queued.append(source)
        else:
            skipped.append(reason)

    if not queued and skipped:
        resp = HTMLResponse("", status_code=409)
        resp.headers["HX-Trigger"] = greentechhub_ui.toast(
            "All scrapers busy or on cooldown", "warning"
        )
        return resp

    msg = f"Queued: {', '.join(queued)}"
    if skipped:
        msg += f" · Skipped {len(skipped)} (busy/cooldown)"

    resp = HTMLResponse("", status_code=204)
    resp.headers["HX-Trigger"] = greentechhub_ui.toast(msg)
    return resp
