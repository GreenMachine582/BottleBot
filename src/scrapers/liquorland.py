from .coles_group import ColesGroupScraper


class LiquorlandScraper(ColesGroupScraper):
    retailer = "liquorland"
    DEALS_URL = "https://www.liquorland.com.au/specials"
