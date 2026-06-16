import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from ...scoring.criteria import Criteria, load_criteria
from ..templating import templates

router = APIRouter()

CRITERIA_PATH = "config/criteria.yaml"


@router.get("/criteria", response_class=HTMLResponse)
async def get_criteria(request: Request):
    criteria = load_criteria(CRITERIA_PATH)
    return templates.TemplateResponse(request, "criteria.html", {
        "criteria": criteria,
        "error": None,
    })


@router.post("/criteria", response_class=HTMLResponse)
async def update_criteria(
    request: Request,
    min_deal_score: float = Form(...),
    immediate_threshold: float = Form(...),
    min_discount_pct: float = Form(...),
    min_saving_aud: float = Form(...),
):
    with open(CRITERIA_PATH) as f:
        raw = yaml.safe_load(f)

    raw.setdefault("alerts", {})["min_deal_score"] = min_deal_score
    raw["alerts"]["immediate_threshold"] = immediate_threshold
    raw.setdefault("thresholds", {})["min_discount_pct"] = min_discount_pct
    raw["thresholds"]["min_saving_aud"] = min_saving_aud

    try:
        Criteria.model_validate(raw)
    except ValidationError as exc:
        criteria = load_criteria(CRITERIA_PATH)
        return templates.TemplateResponse(request, "criteria.html", {
            "criteria": criteria,
            "error": str(exc),
        }, status_code=422)

    with open(CRITERIA_PATH, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return RedirectResponse("/criteria", status_code=303)
