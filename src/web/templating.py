from pathlib import Path

from fastapi.templating import Jinja2Templates

from .utils import clean_product_name
from .watchlist_logic import chip_abv_tooltip, group_name_tooltip, is_volume_watched

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["clean_name"] = clean_product_name
templates.env.globals["is_volume_watched"] = is_volume_watched
templates.env.globals["group_name_tooltip"] = group_name_tooltip
templates.env.globals["chip_abv_tooltip"] = chip_abv_tooltip
