import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.matching import find_matching_product, normalise_name
from src.db.models import Base, Product


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_normalise_name_strips_volume_punctuation_and_case():
    assert normalise_name("Johnnie Walker Black Label, 700mL") == "johnnie walker black label"
    assert normalise_name("Penfolds Bin 389 1L") == "penfolds bin 389"


def test_find_matching_product_returns_none_without_volume(session):
    session.add(Product(name="Johnnie Walker Black Label", brand="Johnnie Walker", volume_ml=700))
    session.commit()

    result = find_matching_product(session, "Johnnie Walker Black Label", "Johnnie Walker", None)
    assert result is None


def test_find_matching_product_returns_none_when_no_candidates(session):
    result = find_matching_product(session, "Some Whisky 700mL", "Some Brand", 700)
    assert result is None


def test_find_matching_product_matches_same_bottle_from_other_retailer(session):
    existing = Product(
        name="Johnnie Walker Black Label 700mL", brand="Johnnie Walker", volume_ml=700
    )
    session.add(existing)
    session.commit()

    # Same bottle, slightly different name formatting from a different retailer.
    result = find_matching_product(
        session, "Johnnie Walker Black Label Whisky 700mL", "Johnnie Walker", 700
    )
    assert result is not None
    assert result.id == existing.id


def test_find_matching_product_requires_exact_volume(session):
    session.add(Product(name="Johnnie Walker Black Label", brand="Johnnie Walker", volume_ml=700))
    session.commit()

    # Same name, different volume — must not match.
    result = find_matching_product(session, "Johnnie Walker Black Label", "Johnnie Walker", 1000)
    assert result is None


def test_find_matching_product_does_not_match_unrelated_product(session):
    session.add(Product(name="Penfolds Bin 389", brand="Penfolds", volume_ml=750))
    session.commit()

    result = find_matching_product(session, "Some Other Wine", "Some Other Brand", 750)
    assert result is None
