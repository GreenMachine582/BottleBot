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


def send_alert(apobj: apprise.Apprise, deal: DealScore, base_url: str, tag: str = "immediate"):
    title, body = build_message(deal, base_url)
    apobj.notify(title=title, body=body, body_format=apprise.NotifyFormat.MARKDOWN, tag=tag)
