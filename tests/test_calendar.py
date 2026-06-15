from datetime import date, timedelta

from dateutil.easter import easter

from src.calendar import EASTER_LEAD_DAYS, EASTER_TRAIL_DAYS, SaleCalendar


def test_eofy_window():
    cal = SaleCalendar()
    assert cal.current_window(date(2026, 6, 15)) == "EOFY"
    assert cal.current_window(date(2026, 6, 30)) == "EOFY"
    assert cal.current_window(date(2026, 6, 14)) is None


def test_boxing_day_window():
    cal = SaleCalendar()
    assert cal.current_window(date(2026, 12, 26)) == "Boxing Day"
    assert cal.current_window(date(2026, 12, 31)) == "Boxing Day"
    assert cal.current_window(date(2026, 12, 25)) is None


def test_new_year_window():
    cal = SaleCalendar()
    assert cal.current_window(date(2026, 1, 1)) == "New Year"
    assert cal.current_window(date(2026, 1, 7)) == "New Year"
    assert cal.current_window(date(2026, 1, 8)) is None


def test_click_frenzy_window():
    cal = SaleCalendar()
    assert cal.current_window(date(2026, 11, 10)) == "Click Frenzy"
    assert cal.current_window(date(2026, 11, 14)) == "Click Frenzy"
    assert cal.current_window(date(2026, 11, 15)) is None


def test_easter_window():
    """Easter is a moveable feast — compute the expected window from dateutil
    rather than hardcoding a historical date."""
    cal = SaleCalendar()
    year = 2026
    sunday = easter(year)
    good_friday = sunday - timedelta(days=2)
    easter_monday = sunday + timedelta(days=1)
    start = good_friday - timedelta(days=EASTER_LEAD_DAYS)
    end = easter_monday + timedelta(days=EASTER_TRAIL_DAYS)

    assert cal.current_window(start) == "Easter"
    assert cal.current_window(end) == "Easter"
    assert cal.current_window(start - timedelta(days=1)) is None
    assert cal.current_window(end + timedelta(days=1)) is None


def test_is_sale_window():
    cal = SaleCalendar()
    assert cal.is_sale_window(date(2026, 6, 20)) is True
    assert cal.is_sale_window(date(2026, 8, 1)) is False
