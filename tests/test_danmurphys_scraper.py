import json

from src.scrapers.danmurphys import _parse_breadcrumb_category, _parse_ld_brand


def test_parse_ld_brand_extracts_name():
    ld = json.dumps({"@type": "product", "brand": {"@type": "Organization", "name": "Secret Tracks"}})
    assert _parse_ld_brand(ld) == "Secret Tracks"


def test_parse_ld_brand_handles_missing_brand():
    ld = json.dumps({"@type": "product", "name": "Some Product"})
    assert _parse_ld_brand(ld) is None


def test_parse_ld_brand_handles_invalid_json():
    assert _parse_ld_brand("not json") is None
    assert _parse_ld_brand(None) is None


def test_parse_breadcrumb_category_with_subcategory():
    category, subcategory = _parse_breadcrumb_category(["Red Wine", "Cabernet Sauvignon"])
    assert category == "wine_red"
    assert subcategory == "Cabernet Sauvignon"


def test_parse_breadcrumb_category_with_only_top_level():
    category, subcategory = _parse_breadcrumb_category(["Beer"])
    assert category == "beer"
    assert subcategory is None


def test_parse_breadcrumb_category_with_no_crumbs():
    assert _parse_breadcrumb_category([]) == (None, None)


def test_parse_breadcrumb_category_strips_whitespace():
    category, subcategory = _parse_breadcrumb_category(["  Gin  ", " London Dry "])
    assert category == "gin"
    assert subcategory == "London Dry"
