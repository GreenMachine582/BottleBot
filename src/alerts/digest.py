import apprise

from ..scoring.criteria import Criteria
from ..scoring.engine import DealScore


def send_digest(apobj: apprise.Apprise, deals: list[DealScore], criteria: Criteria):
    """Send the top N deals as a single daily digest notification."""
    top = deals[: criteria.alerts.digest_max_deals]
    if not top:
        return

    base_url = criteria.web.base_url
    lines = [f"**BottleBot Daily Digest — Top {len(top)} deals**\n"]
    for i, d in enumerate(top, 1):
        dashboard_url = f"{base_url}/deals/{d.retailer_product_id}"
        lines.append(
            f"{i}. **{d.product_name}** — ${d.current_price:.2f} · "
            f"{d.real_discount_pct:.0f}% off · Score {d.score}\n"
            f"   [Buy at {d.retailer.title()}]({d.url}) · [View on BottleBot]({dashboard_url})"
        )

    apobj.notify(
        title="BottleBot Daily Digest",
        body="\n".join(lines),
        body_format=apprise.NotifyFormat.MARKDOWN,
        tag="digest",
    )
