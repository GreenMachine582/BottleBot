import re

# Matches trailing volume strings: "700mL", "700 ml", "1.125L", "1L", "700ML"
_TRAILING_VOLUME_RE = re.compile(
    r"\s*\b\d+(?:\.\d+)?\s*(?:ml|mL|ML|l|L)\b\s*$"
)


def clean_product_name(name: str) -> str:
    """Strip trailing volume strings from a scraped product name for display."""
    cleaned = _TRAILING_VOLUME_RE.sub("", name).strip()
    return cleaned if cleaned else name
