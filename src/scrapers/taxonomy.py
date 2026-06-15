CATEGORY_MAP: dict[str, str] = {
    # Whisky
    "scotch whisky": "whisky",
    "scotch": "whisky",
    "bourbon": "whisky",
    "american whiskey": "whisky",
    "irish whiskey": "whisky",
    "japanese whisky": "whisky",
    "single malt": "whisky",
    "blended whisky": "whisky",
    "tennessee whiskey": "whisky",
    # Wine
    "red wine": "wine_red",
    "reds": "wine_red",
    "white wine": "wine_white",
    "whites": "wine_white",
    "sparkling wine": "wine_sparkling",
    "champagne": "wine_sparkling",
    "prosecco": "wine_sparkling",
    "rosé": "wine_rose",
    "rose": "wine_rose",
    "fortified": "wine_fortified",
    "port": "wine_fortified",
    # Beer
    "beer": "beer",
    "craft beer": "beer",
    "lager": "beer",
    "ale": "beer",
    "ipa": "beer",
    "stout": "beer",
    "cider": "cider",
    # Spirits
    "gin": "gin",
    "vodka": "vodka",
    "rum": "rum",
    "tequila": "tequila",
    "brandy": "brandy",
    "cognac": "brandy",
    "liqueur": "liqueur",
    # Other
    "rtd": "rtd",
    "ready to drink": "rtd",
    "premix": "rtd",
}


def normalise_category(raw: str) -> str:
    return CATEGORY_MAP.get(raw.lower().strip(), raw.lower().replace(" ", "_"))
