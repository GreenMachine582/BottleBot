from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ...db.engine import engine
from ...db.models import ScrapeRun
from ..templating import templates

router = APIRouter()


@router.get("/health", response_class=HTMLResponse)
async def health(request: Request):
    with Session(engine) as session:
        runs = (
            session.query(ScrapeRun)
            .order_by(ScrapeRun.started_at.desc())
            .limit(30)
            .all()
        )
        session.expunge_all()

    return templates.TemplateResponse(request, "health.html", {
        "runs": runs,
    })
