from .coles_group import ColesGroupScraper


class VintageCellarsScraper(ColesGroupScraper):
    retailer = "vintagecellars"
    DEALS_URL = "https://www.vintagecellars.com.au/specials"
