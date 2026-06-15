from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class AlertsConfig(BaseModel):
    min_deal_score: float = 65
    immediate_threshold: float = 85
    digest_time: str = "08:00"
    digest_max_deals: int = 10


class WebConfig(BaseModel):
    base_url: str = "http://localhost:8080"


class ScoringWeights(BaseModel):
    real_discount_pct: float = 0.35
    cpl_rating: float = 0.30
    bulk_value: float = 0.20
    category_pref: float = 0.15


class ScoringModifiers(BaseModel):
    watchlist_bonus: float = 20
    eofy_window_bonus: float = 10
    new_low_bonus: float = 15


class ScoringConfig(BaseModel):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    modifiers: ScoringModifiers = Field(default_factory=ScoringModifiers)


class Thresholds(BaseModel):
    min_discount_pct: float = 20
    min_saving_aud: float = 10
    max_cpl_aud: dict[str, float] = Field(default_factory=lambda: {"default": 30})


class WatchlistConfig(BaseModel):
    products: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class BrandsConfig(BaseModel):
    blocklist: list[str] = Field(default_factory=list)
    allowlist: list[str] = Field(default_factory=list)


class Criteria(BaseModel):
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    categories: dict[str, float] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    brands: BrandsConfig = Field(default_factory=BrandsConfig)


def load_criteria(path: str | Path = "config/criteria.yaml") -> Criteria:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Criteria.model_validate(data)
