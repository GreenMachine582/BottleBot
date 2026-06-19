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

    body = "\n".join(lines)
    apobj.notify(
        title="BottleBot Daily Digest",
        body=body,
        body_format=apprise.NotifyFormat.MARKDOWN,
        tag="digest",
    )

    try:
        from .notify import _log_notification
        _log_notification(
            tag="digest",
            product_name=f"Daily digest ({len(top)} deals)",
            retailer_product_id=None,
            score=None,
            price_aud=None,
            body=body,
            channel="discord+ntfy",
        )
    except Exception:
        pass
