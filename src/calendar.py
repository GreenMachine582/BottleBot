from datetime import date, timedelta

from dateutil.easter import easter

# Fixed-date sale windows: (label, month, day_start, day_end)
FIXED_SALE_WINDOWS = [
    ("EOFY", 6, 15, 30),
    ("Boxing Day", 12, 26, 31),
    ("New Year", 1, 1, 7),
    ("Click Frenzy", 11, 10, 14),
]

# Easter is a moveable feast — compute it per-year with dateutil rather than
# hardcoding a date range. Window covers the lead-up through the long weekend.
EASTER_LEAD_DAYS = 4  # Sale window starts this many days before Good Friday
EASTER_TRAIL_DAYS = 1  # ...and ends this many days after Easter Monday


class SaleCalendar:
    def _easter_window(self, year: int) -> tuple[date, date]:
        sunday = easter(year)
        good_friday = sunday - timedelta(days=2)
        easter_monday = sunday + timedelta(days=1)
        return (
            good_friday - timedelta(days=EASTER_LEAD_DAYS),
            easter_monday + timedelta(days=EASTER_TRAIL_DAYS),
        )

    def is_sale_window(self, d: date | None = None) -> bool:
        return self.current_window(d) is not None

    def current_window(self, d: date | None = None) -> str | None:
        d = d or date.today()
        for label, month, start, end in FIXED_SALE_WINDOWS:
            if d.month == month and start <= d.day <= end:
                return label

        start, end = self._easter_window(d.year)
        if start <= d <= end:
            return "Easter"
        return None
