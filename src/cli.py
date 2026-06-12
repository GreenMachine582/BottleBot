import typer

from .scheduler import run_scraper
from .scrapers.danmurphys import DanMurphysScraper

app = typer.Typer(help="BottleBot CLI")

SCRAPERS = {
    "danmurphys": DanMurphysScraper,
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


if __name__ == "__main__":
    app()
