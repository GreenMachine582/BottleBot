from pathlib import Path

import greentechhub_ui
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from .utils import clean_product_name
from .watchlist_logic import chip_abv_tooltip, group_name_tooltip, is_volume_watched

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.loader = ChoiceLoader(
    [
        templates.env.loader,
        FileSystemLoader(greentechhub_ui.templates_path),
        FileSystemLoader(greentechhub_ui.components_path),
    ]
)
templates.env.globals["clean_name"] = clean_product_name
templates.env.globals["is_volume_watched"] = is_volume_watched
templates.env.globals["group_name_tooltip"] = group_name_tooltip
templates.env.globals["chip_abv_tooltip"] = chip_abv_tooltip

# greentechhub-ui shared shell context — see greentechhub-ui/docs/contract.md
templates.env.globals["brand"] = greentechhub_ui.theme.brand_context(service_name="BottleBot")
templates.env.globals["nav_items"] = [
    {"label": "Deals", "url": "/", "icon": "cart"},
    {"label": "Watchlist", "url": "/watchlist", "icon": "star"},
    {"label": "Criteria", "url": "/criteria", "icon": "sliders"},
    {"label": "Health", "url": "/health", "icon": "activity"},
]
templates.env.globals["theme_css_url"] = "/gth-static/theme.css"
templates.env.globals["icons_css_url"] = "/gth-assets/icons/bootstrap-icons.min.css"
templates.env.globals["toast_js_url"] = "/gth-assets/js/toast.js"
