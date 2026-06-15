import pytest

from src.scrapers.taxonomy import normalise_category


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Scotch Whisky", "whisky"),
        ("BOURBON", "whisky"),
        ("Red Wine", "wine_red"),
        ("Champagne", "wine_sparkling"),
        ("Craft Beer", "beer"),
        ("Gin", "gin"),
        ("Ready to Drink", "rtd"),
    ],
)
def test_normalise_category_known_values(raw, expected):
    assert normalise_category(raw) == expected


def test_normalise_category_unknown_value_falls_back_to_slug():
    assert normalise_category("Some New Category") == "some_new_category"
