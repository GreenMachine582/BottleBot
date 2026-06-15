from unittest.mock import MagicMock

import apprise

from src.alerts.digest import send_digest
from src.alerts.notify import build_apprise, build_message
from src.config.settings import Settings
from src.scoring.criteria import Criteria
from src.scoring.engine import DealScore


def make_deal_score(**overrides) -> DealScore:
    defaults = dict(
        retailer_product_id=42,
        product_name="Test Whisky 700mL",
        retailer="danmurphys",
        url="https://example.com/p/123",
        current_price=50.0,
        avg_90d_price=70.0,
        real_discount_pct=28.6,
        retailer_discount_pct=10.0,
        cpl_aud=71.43,
        category="whisky",
        volume_ml=700,
        promo_label="Member Special",
        score=72.0,
        score_breakdown={},
        is_watchlist=False,
        is_new_low=False,
        bulk_saving_12=0.0,
    )
    defaults.update(overrides)
    return DealScore(**defaults)


def test_build_message_hot_deal_uses_fire_emoji():
    title, _ = build_message(make_deal_score(score=90.0), "http://localhost:8080")
    assert title.startswith("🔥")


def test_build_message_normal_deal_uses_beer_emoji():
    title, _ = build_message(make_deal_score(score=72.0), "http://localhost:8080")
    assert title.startswith("🍺")


def test_build_message_includes_cpl_when_present():
    _, body = build_message(make_deal_score(cpl_aud=71.43), "http://localhost:8080")
    assert "$71.43/L" in body


def test_build_message_omits_cpl_when_absent():
    _, body = build_message(make_deal_score(cpl_aud=None), "http://localhost:8080")
    assert "/L" not in body


def test_build_message_watchlist_and_new_low_flags():
    _, body = build_message(
        make_deal_score(is_watchlist=True, is_new_low=True), "http://localhost:8080"
    )
    assert "⭐ Watchlist item" in body
    assert "📉 All-time low price" in body


def test_build_message_omits_flags_when_false():
    _, body = build_message(
        make_deal_score(is_watchlist=False, is_new_low=False, bulk_saving_12=0.0),
        "http://localhost:8080",
    )
    assert "Watchlist" not in body
    assert "All-time low" not in body
    assert "Buy 12" not in body


def test_build_message_bulk_saving_line():
    _, body = build_message(make_deal_score(bulk_saving_12=120.0), "http://localhost:8080")
    assert "Buy 12 → save $120" in body


def test_build_message_footer_links():
    _, body = build_message(
        make_deal_score(
            retailer="danmurphys", retailer_product_id=42, url="https://example.com/p/123"
        ),
        "http://localhost:8080",
    )
    assert "[Buy at Danmurphys](https://example.com/p/123)" in body
    assert "[View on BottleBot](http://localhost:8080/deals/42)" in body


def test_build_apprise_empty_settings_has_no_targets():
    settings = Settings(_env_file=None, discord_webhook_url="", ntfy_url="")
    assert len(build_apprise(settings)) == 0


def test_build_apprise_adds_discord_target():
    settings = Settings(_env_file=None, discord_webhook_url="discord://123456/abcdef", ntfy_url="")
    assert len(build_apprise(settings)) == 1


def test_build_apprise_adds_both_targets():
    settings = Settings(
        _env_file=None,
        discord_webhook_url="discord://123456/abcdef",
        ntfy_url="ntfy://ntfy.sh/bottlebot-deals",
    )
    assert len(build_apprise(settings)) == 2


def test_send_digest_skips_notify_when_no_deals():
    apobj = MagicMock()
    send_digest(apobj, [], Criteria())
    apobj.notify.assert_not_called()


def test_send_digest_sends_top_n_deals():
    apobj = MagicMock()
    deals = [make_deal_score(product_name=f"Deal {i}", score=float(100 - i)) for i in range(5)]
    criteria = Criteria.model_validate({"alerts": {"digest_max_deals": 3}})

    send_digest(apobj, deals, criteria)

    apobj.notify.assert_called_once()
    _, kwargs = apobj.notify.call_args
    assert kwargs["title"] == "BottleBot Daily Digest"
    assert kwargs["tag"] == "digest"
    assert kwargs["body_format"] == apprise.NotifyFormat.MARKDOWN
    assert "Top 3 deals" in kwargs["body"]
    assert "Deal 0" in kwargs["body"]
    assert "Deal 2" in kwargs["body"]
    assert "Deal 3" not in kwargs["body"]
