import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...db.engine import engine
from ...db.models import Product
from ...scoring.criteria import load_criteria
from ..templating import templates

router = APIRouter()

CRITERIA_PATH = "config/criteria.yaml"


@router.get("/watchlist", response_class=HTMLResponse)
async def get_watchlist(request: Request):
    criteria = load_criteria(CRITERIA_PATH)
    return templates.TemplateResponse(request, "watchlist.html", {
        "products": criteria.watchlist.products,
        "categories": criteria.watchlist.categories,
    })


@router.get("/watchlist/search", response_class=HTMLResponse)
async def search_watchlist(request: Request, q: str = ""):
    products: list[Product] = []
    categories: list[str] = []
    if q.strip():
        with Session(engine) as session:
            products = (
                session.query(Product)
                .filter(Product.name.ilike(f"%{q.strip()}%"))
                .limit(10)
                .all()
            )
            cat_rows = (
                session.query(Product.category)
                .filter(Product.category.ilike(f"%{q.strip()}%"))
                .distinct()
                .limit(8)
                .all()
            )
            categories = [r[0] for r in cat_rows if r[0]]
            session.expunge_all()
    return templates.TemplateResponse(request, "_watchlist_search_results.html", {
        "products": products,
        "categories": categories,
        "q": q.strip(),
    })


@router.post("/watchlist/add")
async def add_to_watchlist(
    product_name: str = Form(default=""),
    category: str = Form(default=""),
):
    with open(CRITERIA_PATH) as f:
        raw = yaml.safe_load(f)

    raw.setdefault("watchlist", {})

    product_name = product_name.strip()
    if product_name:
        raw["watchlist"].setdefault("products", [])
        if product_name not in raw["watchlist"]["products"]:
            raw["watchlist"]["products"].append(product_name)

    category = category.strip()
    if category:
        raw["watchlist"].setdefault("categories", [])
        if category not in raw["watchlist"]["categories"]:
            raw["watchlist"]["categories"].append(category)

    with open(CRITERIA_PATH, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return RedirectResponse("/watchlist", status_code=303)


@router.post("/watchlist/remove")
async def remove_from_watchlist(
    product_name: str = Form(default=""),
    category: str = Form(default=""),
):
    with open(CRITERIA_PATH) as f:
        raw = yaml.safe_load(f)

    wl = raw.get("watchlist", {})
    product_name = product_name.strip()
    if product_name and product_name in wl.get("products", []):
        wl["products"].remove(product_name)

    category = category.strip()
    if category and category in wl.get("categories", []):
        wl["categories"].remove(category)

    with open(CRITERIA_PATH, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return RedirectResponse("/watchlist", status_code=303)
