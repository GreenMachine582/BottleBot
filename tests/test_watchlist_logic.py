import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, Product
from src.web.watchlist_logic import (
    find_siblings,
    group_products,
    is_volume_watched,
    toggle_volume_off,
    toggle_volume_on,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def make_product(session, name, brand="Penfolds", category="wine_red", volume_ml=750):
    p = Product(name=name, brand=brand, category=category, volume_ml=volume_ml)
    session.add(p)
    session.flush()
    return p


def test_group_products_groups_by_clean_name_and_brand(session):
    p1 = make_product(session, "Penfolds Bin 389 750mL", volume_ml=750)
    p2 = make_product(session, "Penfolds Bin 389 1L", volume_ml=1000)
    p3 = make_product(session, "Jameson 700mL", brand="Jameson", category="whisky", volume_ml=700)
    session.commit()

    groups = group_products([p1, p2, p3])
    assert len(groups) == 2
    bin389 = next(g for g in groups if g.clean_name == "Penfolds Bin 389")
    assert [v.id for v in bin389.volumes] == [p1.id, p2.id]


def test_is_volume_watched_direct_match():
    p = Product(name="Jameson 700mL", volume_ml=700)
    assert is_volume_watched(p, ["Jameson 700mL"]) is True
    assert is_volume_watched(p, ["Jameson 1L"]) is False


def test_is_volume_watched_blanket_match():
    p = Product(name="Jameson 700mL", volume_ml=700)
    assert is_volume_watched(p, ["Jameson"]) is True


def test_toggle_volume_on_adds_full_name():
    p = Product(name="Jameson 700mL", volume_ml=700)
    assert toggle_volume_on([], p) == ["Jameson 700mL"]


def test_toggle_volume_on_is_noop_when_blanket_covers_it():
    p = Product(name="Jameson 700mL", volume_ml=700)
    assert toggle_volume_on(["Jameson"], p) == ["Jameson"]


def test_toggle_volume_off_removes_direct_entry():
    p = Product(name="Jameson 700mL", volume_ml=700)
    assert toggle_volume_off(["Jameson 700mL"], p, siblings=[p]) == []


def test_toggle_volume_off_expands_blanket_to_remaining_siblings(session):
    p1 = make_product(session, "Jameson 700mL", brand="Jameson", category="whisky", volume_ml=700)
    p2 = make_product(session, "Jameson 1L", brand="Jameson", category="whisky", volume_ml=1000)
    session.commit()

    result = toggle_volume_off(["Jameson"], p1, siblings=[p1, p2])
    assert "Jameson" not in result
    assert p1.name not in result
    assert p2.name in result


def test_find_siblings_matches_by_clean_name_and_brand(session):
    p1 = make_product(session, "Jameson 700mL", brand="Jameson", category="whisky", volume_ml=700)
    p2 = make_product(session, "Jameson 1L", brand="Jameson", category="whisky", volume_ml=1000)
    other = make_product(session, "Jim Beam 700mL", brand="Jim Beam", category="whisky", volume_ml=700)
    session.commit()

    siblings = find_siblings(session, p1)
    ids = {s.id for s in siblings}
    assert ids == {p1.id, p2.id}
    assert other.id not in ids
