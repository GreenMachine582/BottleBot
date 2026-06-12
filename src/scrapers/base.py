from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class ScrapedProduct:
    retailer: str
    retailer_sku: str
    url: str
    name: str
    brand: str | None
    category: str | None
    volume_ml: int | None
    abv: float | None
    price_aud: float
    was_price_aud: float | None
    in_stock: bool
    on_sale: bool
    promo_label: str | None
    image_url: str | None


class BaseScraper(ABC):
    retailer: str = ""

    @abstractmethod
    def scrape_deals(self) -> Iterator[ScrapedProduct]:
        """Yield products currently on deal / in the deals section."""
        ...

    @abstractmethod
    def scrape_category(self, category: str) -> Iterator[ScrapedProduct]:
        """Yield all products in a given category (for baseline price tracking)."""
        ...

    def scrape_all(self) -> Iterator[ScrapedProduct]:
        """Default: scrape deals only. Override for full catalogue."""
        yield from self.scrape_deals()
