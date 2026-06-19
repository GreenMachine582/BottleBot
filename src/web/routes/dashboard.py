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

    categories = sorted({d.category for d in deals if d.category})
    retailers = sorted({d.retailer for d in deals})

    return templates.TemplateResponse(request, "dashboard.html", {
        "deals": deals[:100],
        "min_score": criteria.alerts.min_deal_score,
        "configured_base_url": configured,
        "base_url_mismatch": configured != actual,
        "categories": categories,
        "retailers": retailers,
    })


@router.get("/deals/filter", response_class=HTMLResponse)
async def filter_deals(
    request: Request,
    q: str = "",
    category: str = "",
    retailer: str = "",
    min_score: float = 0,
):
    criteria = load_criteria()
    with Session(engine) as session:
        deals = ScoringEngine(session, criteria).score_all_current_deals()

    if q:
        q_lower = q.lower()
        deals = [
            d for d in deals
            if q_lower in d.product_name.lower()
            or (d.category and q_lower in d.category.lower())
            or (d.volume_ml and q_lower in str(d.volume_ml))
        ]
    if category:
        deals = [d for d in deals if d.category == category]
    if retailer:
        deals = [d for d in deals if d.retailer == retailer]
    if min_score:
        deals = [d for d in deals if d.score >= min_score]

    return templates.TemplateResponse(request, "_deals_table.html", {
        "deals": deals[:100],
    })
