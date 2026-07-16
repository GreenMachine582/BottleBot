from urllib.parse import urlencode

import greentechhub_ui
import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ...db.engine import engine
from ...db.models import Product
from ...scoring.criteria import load_criteria
from ...scrapers.taxonomy import CATEGORIES, CATEGORY_LABELS
from ..templating import templates
from ..watchlist_logic import (
    ProductGroup,
    find_siblings,
    group_products,
    is_volume_watched,
    toggle_volume_off,
    toggle_volume_on,
)

router = APIRouter()

CRITERIA_PATH = "config/criteria.yaml"
WATCHLIST_PAGE_SIZE = 20


def _paginate(
    groups: list[ProductGroup],
    offset: int,
    q: str,
    category: str,
    watchlist_only: bool,
) -> dict:
    """Slices `groups` to one page and builds the "load more" URL for the
    next page (carrying the current filters), or None if this was the last."""
    total = len(groups)
    page = groups[offset: offset + WATCHLIST_PAGE_SIZE]
    next_offset = offset + WATCHLIST_PAGE_SIZE
    next_url = None
    if next_offset < total:
        params = {"offset": next_offset}
        if q:
            params["q"] = q
        if category:
            params["category"] = category
        if watchlist_only:
            params["watchlist_only"] = "true"
        next_url = "/watchlist/list?" + urlencode(params)
    return {"groups": page, "next_url": next_url}


def _load_yaml() -> dict:
    with open(CRITERIA_PATH) as f:
        return yaml.safe_load(f)


def _save_yaml(raw: dict) -> None:
    with open(CRITERIA_PATH, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


@router.get("/watchlist", response_class=HTMLResponse)
async def get_watchlist(request: Request):
    criteria = load_criteria(CRITERIA_PATH)
    with Session(engine) as session:
        products = session.query(Product).order_by(Product.name).all()
        groups = group_products(products)
        session.expunge_all()

    return templates.TemplateResponse(request, "watchlist.html", {
        "categories": CATEGORIES,
        "category_labels": CATEGORY_LABELS,
        "watched_categories": {c.lower() for c in criteria.watchlist.categories},
        "watch_products": criteria.watchlist.products,
        **_paginate(groups, 0, "", "", False),
    })


@router.get("/watchlist/list", response_class=HTMLResponse)
async def filter_watchlist_list(
    request: Request,
    q: str = "",
    category: str = "",
    watchlist_only: bool = False,
    offset: int = 0,
):
    criteria = load_criteria(CRITERIA_PATH)
    watch_products = criteria.watchlist.products

    with Session(engine) as session:
        query = session.query(Product)
        if q.strip():
            query = query.filter(Product.name.ilike(f"%{q.strip()}%"))
        if category:
            query = query.filter(Product.category == category)
        products = query.order_by(Product.name).all()
        groups = group_products(products)
        session.expunge_all()

    if watchlist_only:
        narrowed = []
        for g in groups:
            watched_vols = [v for v in g.volumes if is_volume_watched(v, watch_products)]
            if watched_vols:
                narrowed.append(ProductGroup(g.clean_name, g.brand, g.category, g.subcategory, watched_vols))
        groups = narrowed

    return templates.TemplateResponse(request, "_watchlist_list.html", {
        "watch_products": watch_products,
        "category_labels": CATEGORY_LABELS,
        **_paginate(groups, offset, q, category, watchlist_only),
    })


@router.post("/watchlist/toggle-category")
async def toggle_category(request: Request, category: str = Form(...)):
    if category not in CATEGORIES:
        return HTMLResponse("", status_code=404)

    raw = _load_yaml()
    raw.setdefault("watchlist", {})
    raw["watchlist"].setdefault("categories", [])
    cats = raw["watchlist"]["categories"]

    if any(c.lower() == category for c in cats):
        raw["watchlist"]["categories"] = [c for c in cats if c.lower() != category]
        now_on = False
    else:
        cats.append(category)
        now_on = True

    _save_yaml(raw)

    label = CATEGORY_LABELS.get(category, category)
    resp = templates.TemplateResponse(request, "_watchlist_category_pill.html", {
        "cat": category,
        "label": label,
        "watching": now_on,
    })
    resp.headers["HX-Trigger"] = greentechhub_ui.toast(
        f"{label} {'added to' if now_on else 'removed from'} watchlist"
    )
    return resp


@router.post("/watchlist/toggle-volume")
async def toggle_volume(request: Request, product_id: int = Form(...)):
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if product is None:
            return HTMLResponse("", status_code=404)
        siblings = find_siblings(session, product)
        session.expunge_all()

    raw = _load_yaml()
    raw.setdefault("watchlist", {})
    raw["watchlist"].setdefault("products", [])
    watch_products = raw["watchlist"]["products"]

    if is_volume_watched(product, watch_products):
        new_list = toggle_volume_off(watch_products, product, siblings)
        now_on = False
    else:
        new_list = toggle_volume_on(watch_products, product)
        now_on = True

    raw["watchlist"]["products"] = new_list
    _save_yaml(raw)

    resp = templates.TemplateResponse(request, "_watchlist_volume_chip.html", {
        "product": product,
        "watching": now_on,
        "siblings": siblings,
    })
    resp.headers["HX-Trigger"] = greentechhub_ui.toast(
        f"{product.volume_ml}mL {'added to' if now_on else 'removed from'} watchlist"
    )
    return resp
