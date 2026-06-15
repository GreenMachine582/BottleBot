"""Run after each scrape. Called by scheduler or CLI."""

import logging
import time

from sqlalchemy.orm import Session

from .alerts.notify import build_apprise, send_alert
from .config.settings import Settings
from .db.engine import engine
from .scoring.criteria import load_criteria
from .scoring.engine import ScoringEngine

log = logging.getLogger(__name__)


def run_scoring(criteria_path: str = "config/criteria.yaml"):
    criteria = load_criteria(criteria_path)
    apobj = build_apprise(Settings())

    with Session(engine) as session:
        scorer = ScoringEngine(session, criteria)
        deals = scorer.score_all_current_deals()

    log.info("Scored %d deals above threshold %s", len(deals), criteria.alerts.min_deal_score)

    immediate = [d for d in deals if d.score >= criteria.alerts.immediate_threshold]
    digest = [d for d in deals if d.score < criteria.alerts.immediate_threshold]

    # Fire immediately for hot deals
    for deal in immediate:
        log.info("Immediate alert: %s (%s)", deal.product_name, deal.score)
        send_alert(apobj, deal, criteria.web.base_url, tag="immediate")
        time.sleep(0.5)  # be polite to self-hosted ntfy/Discord rate limits

    # Digest goes out at criteria.alerts.digest_time (separate scheduled job calls send_digest)
    return {"immediate": immediate, "digest": digest}
