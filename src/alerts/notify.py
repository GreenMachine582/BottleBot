import apprise

from ..config.settings import Settings
from ..scoring.engine import DealScore


def build_message(deal: DealScore, base_url: str) -> tuple[str, str]:
    """Build a (title, markdown body) pair for a single deal."""
    title = f"{'🔥' if deal.score >= 85 else '🍺'} {deal.product_name}"

    lines = [
        f"**${deal.current_price:.2f}** — {deal.real_discount_pct:.0f}% off 90-day avg "
        f"(was ${deal.avg_90d_price:.2f})",
        f"Score: **{deal.score}/100**",
    ]
    if deal.cpl_aud:
        lines.append(f"${deal.cpl_aud:.2f}/L")
    if deal.is_watchlist:
        lines.append("⭐ Watchlist item")
    if deal.is_new_low:
        lines.append("📉 All-time low price")
    if deal.bulk_saving_12 > 0:
        lines.append(f"Buy 12 → save ${deal.bulk_saving_12:.0f}")

    dashboard_url = f"{base_url}/deals/{deal.retailer_product_id}"
    lines.append(
        f"\n[Buy at {deal.retailer.title()}]({deal.url}) · [View on BottleBot]({dashboard_url})"
    )

    return title, "\n".join(lines)


def build_apprise(settings: Settings) -> apprise.Apprise:
    """Assemble notification targets from .env-sourced settings."""
    apobj = apprise.Apprise()
    if settings.discord_webhook_url:
        apobj.add(settings.discord_webhook_url, tag=["immediate", "digest"])
    if settings.ntfy_url:
        apobj.add(settings.ntfy_url, tag=["digest"])
    return apobj


def _log_notification(
    tag: str,
    product_name: str,
    retailer_product_id: int | None,
    score: float | None,
    price_aud: float | None,
    body: str,
    channel: str,
) -> None:
    from ..db.engine import engine
    from ..db.models import NotificationLog
    from datetime import datetime
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        s.add(NotificationLog(
            dispatched_at=datetime.utcnow(),
            channel=channel,
            tag=tag,
            product_name=product_name,
            retailer_product_id=retailer_product_id,
            score=score,
            price_aud=price_aud,
            message_body=body,
        ))
        s.commit()


def send_alert(
    apobj: apprise.Apprise,
    deal: DealScore,
    base_url: str,
    tag: str = "immediate",
    settings: Settings | None = None,
):
    title, body = build_message(deal, base_url)
    apobj.notify(title=title, body=body, body_format=apprise.NotifyFormat.MARKDOWN, tag=tag)

    if settings is None:
        settings = Settings()
    channel_parts = []
    if settings.discord_webhook_url:
        channel_parts.append("discord")
    if settings.ntfy_url:
        channel_parts.append("ntfy")
    channel = "+".join(channel_parts) or "unknown"

    try:
        _log_notification(
            tag=tag,
            product_name=deal.product_name,
            retailer_product_id=deal.retailer_product_id,
            score=deal.score,
            price_aud=deal.current_price,
            body=body,
            channel=channel,
        )
    except Exception:
        pass
