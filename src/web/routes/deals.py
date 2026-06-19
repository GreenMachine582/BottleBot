from datetime import datetime, timedelta

import plotly.graph_objects as go
import plotly.io as pio
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...db.engine import engine
from ...db.models import PriceHistory, RetailerProduct
from ...scoring.criteria import load_criteria
from ...scoring.cross_retailer import compare_product_across_retailers
from ...scoring.engine import ScoringEngine
from ..templating import templates

router = APIRouter()

_DEFAULT_QUANTITIES = [1, 6, 12, 24]


def _build_price_chart(history: list) -> str:
    dates = [h.scraped_at for h in history]
    prices = [h.price_aud for h in history]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=prices,
        mode="lines+markers",
        name="Price",
        line={"color": "#5BCAA5", "width": 2},
        marker={"size": 4},
    ))
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        height=220,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"showgrid": False},
        yaxis={"showgrid": True, "gridcolor": "rgba(128,128,128,0.15)", "tickprefix": "$"},
        font={"family": "system-ui", "size": 12},
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False, div_id="price-chart")


def _get_avg_nd(session: Session, retailer_product_id: int, days: int) -> float | None:
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = session.query(func.avg(PriceHistory.price_aud)).filter(
        PriceHistory.retailer_product_id == retailer_product_id,
        PriceHistory.scraped_at >= cutoff,
    ).scalar()
    return float(result) if result is not None else None


@router.get("/deals/{retailer_product_id}", response_class=HTMLResponse)
async def deal_detail(request: Request, retailer_product_id: int):
    criteria = load_criteria()
    with Session(engine) as session:
        rp = session.get(RetailerProduct, retailer_product_id)
        if not rp:
            return HTMLResponse("Not found", status_code=404)

        history = (
            session.query(PriceHistory)
            .filter_by(retailer_product_id=retailer_product_id)
            .order_by(PriceHistory.scraped_at)
            .all()
        )
        latest = history[-1] if history else None
        cross = compare_product_across_retailers(session, rp.product_id, current_rp_id=retailer_product_id)
        avg_90d = _get_avg_nd(session, retailer_product_id, 90)
        avg_30d = _get_avg_nd(session, retailer_product_id, 30)
        all_time_low = session.query(func.min(PriceHistory.price_aud)).filter_by(
            retailer_product_id=retailer_product_id
        ).scalar()
        all_time_high = session.query(func.max(PriceHistory.price_aud)).filter_by(
            retailer_product_id=retailer_product_id
        ).scalar()

        deal_score = None
        if latest:
            try:
                deal_score = ScoringEngine(session, criteria).score_deal(rp, latest)
            except Exception:
                pass

        chart_html = _build_price_chart(history) if len(history) > 1 else None

        session.expunge_all()

    return templates.TemplateResponse(request, "deal.html", {
        "rp": rp,
        "product": rp.product,
        "latest": latest,
        "history": history,
        "chart_html": chart_html,
        "cross": cross,
        "deal_score": deal_score,
        "avg_90d": avg_90d,
        "avg_30d": avg_30d,
        "all_time_low": float(all_time_low) if all_time_low is not None else None,
        "all_time_high": float(all_time_high) if all_time_high is not None else None,
        "quantities": _DEFAULT_QUANTITIES,
        "selected_qty": 12,
        "criteria": criteria,
    })


@router.get("/deals/{retailer_product_id}/bulkcalc", response_class=HTMLResponse)
async def bulk_calc(request: Request, retailer_product_id: int, qty: int = 12):
    with Session(engine) as session:
        rp = session.get(RetailerProduct, retailer_product_id)
        if not rp:
            return HTMLResponse("Not found", status_code=404)
        latest = (
            session.query(PriceHistory)
            .filter_by(retailer_product_id=retailer_product_id)
            .order_by(PriceHistory.scraped_at.desc())
            .first()
        )
        avg_90d = _get_avg_nd(session, retailer_product_id, 90)
        if latest:
            session.expunge(latest)

    qty = max(1, min(qty, 120))
    quantities = sorted(set(_DEFAULT_QUANTITIES + [qty]))

    return templates.TemplateResponse(request, "_bulkcalc_table.html", {
        "latest": latest,
        "avg_90d": avg_90d,
        "quantities": quantities,
        "selected_qty": qty,
    })
