import re

_VOL_RE = re.compile(
    r"(?:case\s+\d+\s+x\s+|(\d+)\s+(?:pack|x)\s+)?(\d+(?:\.\d+)?)\s*(ml|mL|cl|cL|l|L)",
    re.IGNORECASE,
)


def parse_volume_ml(text: str) -> int | None:
    """Extract single-unit volume in mL from a product name/description string.

    Handles packs ("4 Pack 440mL"), cases ("Case 12 x 750mL"), multi-buy
    ("6 x 330mL"), and cl/L/mL units. Returns the volume of a *single* unit,
    not the pack/case total. Returns None if no volume found.
    """
    match = _VOL_RE.search(text)
    if not match:
        return None
    val = float(match.group(2))
    unit = match.group(3).lower()
    if unit == "l":
        return int(val * 1000)
    elif unit == "cl":
        return int(val * 10)
    else:
        return int(val)


def calc_cpl(price_aud: float, volume_ml: int) -> float:
    """Cost per litre."""
    return price_aud / (volume_ml / 1000)
