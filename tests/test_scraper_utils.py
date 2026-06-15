import pytest

from src.scrapers.utils import calc_cpl, parse_volume_ml


@pytest.mark.parametrize(
    "text, expected",
    [
        ("700mL", 700),
        ("700 mL", 700),
        ("70cl", 700),
        ("1L", 1000),
        ("1.125L", 1125),
        ("2L cask", 2000),
        ("375ml", 375),
        ("6 x 330mL", 330),
        ("Case 12 x 750mL", 750),
        ("4 Pack 440mL", 440),
    ],
)
def test_parse_volume_ml(text, expected):
    assert parse_volume_ml(text) == expected


def test_parse_volume_ml_returns_none_when_no_volume_found():
    assert parse_volume_ml("Premium Aged Whisky") is None


def test_calc_cpl_one_litre():
    assert calc_cpl(50.0, 1000) == 50.0


def test_calc_cpl_700ml():
    assert calc_cpl(35.0, 700) == pytest.approx(50.0)
