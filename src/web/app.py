from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..calendar import SaleCalendar
from .routes import criteria, dashboard, deals, health, watchlist
from .templating import templates

_here = Path(__file__).parent

app = FastAPI(title="BottleBot", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_here / "static"), name="static")

# Expose current_sale_window() as a Jinja2 global so base.html can call it
# on every request without each route having to pass it explicitly.
templates.env.globals["current_sale_window"] = lambda: SaleCalendar().current_window()

app.include_router(dashboard.router)
app.include_router(deals.router)
app.include_router(watchlist.router)
app.include_router(criteria.router)
app.include_router(health.router)
