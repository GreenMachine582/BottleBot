import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session

from .db.engine import engine
from .scheduler import run_scraper
from .scoring.criteria import load_criteria
from .scoring.engine import ScoringEngine
from .scrapers.bws import BWSScraper
from .scrapers.cellarmasters import CellarMastersScraper
from .scrapers.danmurphys import DanMurphysScraper
from .scrapers.firstchoice import FirstChoiceScraper
from .scrapers.liquorland import LiquorlandScraper
from .scrapers.vintagecellars import VintageCellarsScraper

app = typer.Typer(help="BottleBot CLI")
console = Console()

SCRAPERS = {
    "danmurphys": DanMurphysScraper,
    "bws": BWSScraper,
    "liquorland": LiquorlandScraper,
    "firstchoice": FirstChoiceScraper,
    "cellarmasters": CellarMastersScraper,
    "vintagecellars": VintageCellarsScraper,
}


@app.callback()
def callback():
    """BottleBot — Australian bottle shop deal scraper."""


@app.command()
def scrape(source: str = typer.Option("danmurphys", help="Scraper source to run")):
    """Run a one-off scrape for the given source."""
    scraper_cls = SCRAPERS.get(source)
    if not scraper_cls:
        typer.echo(f"Unknown source: {source}. Choices: {', '.join(SCRAPERS)}")
        raise typer.Exit(1)
    run_scraper(scraper_cls, source)


@app.command()
def score(
    criteria_path: str = typer.Option("config/criteria.yaml", help="Path to criteria config"),
    top: int = typer.Option(20, help="Number of deals to show"),
):
    """Score current deals and print a ranked table — no alerts are sent."""
    criteria = load_criteria(criteria_path)

    with Session(engine) as session:
        scorer = ScoringEngine(session, criteria)
        deals = scorer.score_all_current_deals()

    table = Table(title=f"Top {min(top, len(deals))} deals")
    table.add_column("Rank", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Discount", justify="right")
    table.add_column("$/L", justify="right")
    table.add_column("Product")
    table.add_column("Retailer")
    table.add_column("Price", justify="right")

    for i, d in enumerate(deals[:top], 1):
        table.add_row(
            str(i),
            f"{d.score:.1f}",
            f"{d.real_discount_pct:.0f}%",
            f"${d.cpl_aud:.2f}" if d.cpl_aud else "—",
            d.product_name,
            d.retailer.title(),
            f"${d.current_price:.2f}",
        )

    console.print(table)


if __name__ == "__main__":
    app()
