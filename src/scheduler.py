import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session

from .alerts.digest import send_digest
from .alerts.notify import build_apprise
from .config.settings import Settings
from .db.engine import engine
from .db.models import Base, ScrapeRun
from .db.writer import upsert_product
from .run_scoring import run_scoring
from .scoring.criteria import load_criteria
from .scoring.engine import ScoringEngine
from .scrapers.bws import BWSScraper
from .scrapers.cellarmasters import CellarMastersScraper
from .scrapers.danmurphys import DanMurphysScraper
from .scrapers.firstchoice import FirstChoiceScraper
from .scrapers.liquorland import LiquorlandScraper
from .scrapers.vintagecellars import VintageCellarsScraper

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

Base.metadata.create_all(engine)


def run_scraper(scraper_cls, source_name: str):
    log.info(f"Starting scrape: {source_name}")
    run = ScrapeRun(source=source_name, started_at=datetime.utcnow(), status="running")
    with Session(engine) as session:
        session.add(run)
        session.commit()
        try:
            scraper = scraper_cls()
            seen = inserted = 0
            for product in scraper.scrape_deals():
                seen += 1
                _, changed = upsert_product(session, product)
                if changed:
                    inserted += 1
            session.commit()
            run.status = "success"
            run.products_seen = seen
            run.prices_inserted = inserted
        except Exception as e:
            run.status = "failed"
            run.error_msg = str(e)
            log.exception(f"Scrape failed: {source_name}")
        finally:
            run.finished_at = datetime.utcnow()
            session.commit()
    log.info(f"Done: {source_name} — {seen} seen, {inserted} new prices")


def run_digest():
    criteria = load_criteria()
    with Session(engine) as session:
        deals = ScoringEngine(session, criteria).score_all_current_deals()
    send_digest(build_apprise(Settings()), deals, criteria)


def main():
    scheduler = BlockingScheduler(timezone="Australia/Sydney")
    now = datetime.now()

    # Stagger start times so retailers aren't all hit at once — each job's
    # own interval stays a clean 6h/12h; only the first run is offset (via
    # next_run_time). Using `hours=6, minutes=15` etc. on "interval" would
    # change the *period* to 6h15m, not just the start time.
    scheduler.add_job(
        run_scraper, "interval", hours=6,
        args=[DanMurphysScraper, "danmurphys"],
        next_run_time=now,
    )
    scheduler.add_job(
        run_scraper, "interval", hours=6,
        args=[BWSScraper, "bws"],
        next_run_time=now + timedelta(minutes=15),
    )
    scheduler.add_job(
        run_scraper, "interval", hours=6,
        args=[LiquorlandScraper, "liquorland"],
        next_run_time=now + timedelta(minutes=30),
    )
    scheduler.add_job(
        run_scraper, "interval", hours=6,
        args=[FirstChoiceScraper, "firstchoice"],
        next_run_time=now + timedelta(minutes=45),
    )
    scheduler.add_job(
        run_scraper, "interval", hours=12,
        args=[CellarMastersScraper, "cellarmasters"],
        next_run_time=now + timedelta(minutes=60),
    )
    scheduler.add_job(
        run_scraper, "interval", hours=12,
        args=[VintageCellarsScraper, "vintagecellars"],
        next_run_time=now + timedelta(minutes=75),
    )

    # Score + fire immediate alerts ~15 minutes after the last scraper starts
    scheduler.add_job(
        run_scoring,
        "interval",
        hours=6,
        next_run_time=now + timedelta(minutes=90),
    )

    # Daily digest at criteria.alerts.digest_time (e.g. "08:00" AEST)
    digest_hour, digest_minute = (int(p) for p in load_criteria().alerts.digest_time.split(":"))
    scheduler.add_job(run_digest, "cron", hour=digest_hour, minute=digest_minute)

    log.info("BottleBot scheduler started. Running every 6 hours.")
    scheduler.start()


if __name__ == "__main__":
    main()
