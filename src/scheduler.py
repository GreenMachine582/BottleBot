import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session

from .db.engine import engine
from .db.models import Base, ScrapeRun
from .db.writer import upsert_product
from .scrapers.danmurphys import DanMurphysScraper

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


def main():
    scheduler = BlockingScheduler(timezone="Australia/Sydney")
    scheduler.add_job(
        run_scraper,
        "interval",
        hours=6,
        args=[DanMurphysScraper, "danmurphys"],
        next_run_time=datetime.now()  # Run immediately on start
    )
    log.info("BottleBot scheduler started. Running every 6 hours.")
    scheduler.start()


if __name__ == "__main__":
    main()
