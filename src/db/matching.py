import logging
import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from .models import Product

log = logging.getLogger(__name__)

# Matches at or above `threshold` but below this are used, but logged for
# manual review — they're more likely to be false positives.
REVIEW_THRESHOLD = 0.92


def normalise_name(name: str) -> str:
    """Strip volume, punctuation, case for comparison."""
    name = name.lower()
    name = re.sub(r"\b\d+\s*(ml|l|litre|liter)\b", "", name)
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def find_matching_product(
    session: Session,
    name: str,
    brand: str | None,
    volume_ml: int | None,
    threshold: float = 0.85,
) -> Product | None:
    """
    Try to find an existing Product that matches an incoming scraped product,
    so the same bottle from a different retailer links to one canonical row.

    Requires an exact volume_ml match before considering fuzzy name/brand
    similarity — without it, a 700mL bottle could fuzzy-match a 1L bottle of
    the same name. If volume_ml is unknown, no match is attempted.
    """
    if not volume_ml:
        return None

    candidates = session.query(Product).filter(Product.volume_ml == volume_ml).all()

    norm_name = normalise_name(f"{brand or ''} {name}")
    best_score = 0.0
    best_match = None

    for candidate in candidates:
        cand_norm = normalise_name(f"{candidate.brand or ''} {candidate.name}")
        similarity = SequenceMatcher(None, norm_name, cand_norm).ratio()
        if similarity > best_score:
            best_score = similarity
            best_match = candidate

    if best_score >= threshold:
        if best_score < REVIEW_THRESHOLD:
            log.info(
                "Low-confidence product match (%.2f): %r -> %r (id=%d)",
                best_score, name, best_match.name, best_match.id,
            )
        return best_match
    return None
