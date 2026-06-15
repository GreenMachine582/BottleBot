from .coles_group import ColesGroupScraper


class FirstChoiceScraper(ColesGroupScraper):
    retailer = "firstchoice"
    DEALS_URL = "https://www.firstchoiceliquor.com.au/specials"
