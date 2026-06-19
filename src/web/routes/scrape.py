import json

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse

from ...scrapers.bws import BWSScraper
from ...scrapers.cellarmasters import CellarMastersScraper
from ...scrapers.danmurphys import DanMurphysScraper
from ...scrapers.firstchoice import FirstChoiceScraper
from ...scrapers.liquorland import LiquorlandScraper
from ...scrapers.vintagecellars import VintageCellarsScraper

router = APIRouter()

_SCRAPERS = {
    "danmurphys": DanMurphysScraper,
    "bws": BWSScraper,
    "liquorland": LiquorlandScraper,
    "firstchoice": FirstChoiceScraper,
    "cellarmasters": CellarMastersScraper,
    "vintagecellars": VintageCellarsScraper,
}


def _run_source(source: str) -> None:
    from ...scheduler import run_scraper
    scraper_cls = _SCRAPERS[source]
    run_scraper(scraper_cls, source)


@router.post("/scrape/trigger/{source}")
async def trigger_scrape(source: str, background_tasks: BackgroundTasks):
    if source not in _SCRAPERS:
        return HTMLResponse("", status_code=404)
    background_tasks.add_task(_run_source, source)
    resp = HTMLResponse("", status_code=204)
    resp.headers["HX-Trigger"] = json.dumps({"showToast": f"Scraper queued for {source}"})
    return resp


@router.post("/scrape/trigger")
async def trigger_all(background_tasks: BackgroundTasks):
    for source in _SCRAPERS:
        background_tasks.add_task(_run_source, source)
    resp = HTMLResponse("", status_code=204)
    resp.headers["HX-Trigger"] = json.dumps({"showToast": "All scrapers queued"})
    return resp
