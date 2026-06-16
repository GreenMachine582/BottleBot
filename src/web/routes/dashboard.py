from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ...db.engine import engine
from ...scoring.criteria import load_criteria
from ...scoring.engine import ScoringEngine
from ..templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    criteria = load_criteria()
    with Session(engine) as session:
        deals = ScoringEngine(session, criteria).score_all_current_deals()

    configured = criteria.web.base_url.rstrip("/")
    actual = str(request.base_url).rstrip("/")

    return templates.TemplateResponse(request, "dashboard.html", {
        "deals": deals[:50],
        "min_score": criteria.alerts.min_deal_score,
        "configured_base_url": configured,
        "base_url_mismatch": configured != actual,
    })
