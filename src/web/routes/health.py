from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ...db.engine import engine
from ...db.models import NotificationLog, ScrapeRun
from ..templating import templates

router = APIRouter()


def _build_timeline(runs: list, logs: list) -> list[dict]:
    events = []
    for r in runs:
        if r.started_at:
            events.append({"type": "scrape", "ts": r.started_at, "run": r, "log": None})
    for lg in logs:
        events.append({"type": "notification", "ts": lg.dispatched_at, "run": None, "log": lg})
    events.sort(key=lambda e: e["ts"] or datetime.min, reverse=True)
    return events[:60]


@router.get("/health", response_class=HTMLResponse)
async def health(request: Request):
    with Session(engine) as session:
        runs = (
            session.query(ScrapeRun)
            .order_by(ScrapeRun.started_at.desc())
            .limit(30)
            .all()
        )
        logs = (
            session.query(NotificationLog)
            .order_by(NotificationLog.dispatched_at.desc())
            .limit(50)
            .all()
        )
        any_running = any(r.status == "running" for r in runs)
        timeline = _build_timeline(runs, logs)
        session.expunge_all()

    return templates.TemplateResponse(request, "health.html", {
        "runs": runs,
        "logs": logs,
        "any_running": any_running,
        "timeline": timeline,
    })


@router.get("/health/runs", response_class=HTMLResponse)
async def health_runs(request: Request):
    with Session(engine) as session:
        runs = (
            session.query(ScrapeRun)
            .order_by(ScrapeRun.started_at.desc())
            .limit(30)
            .all()
        )
        any_running = any(r.status == "running" for r in runs)
        session.expunge_all()

    return templates.TemplateResponse(request, "_scrape_runs_table.html", {
        "runs": runs,
        "any_running": any_running,
    })
