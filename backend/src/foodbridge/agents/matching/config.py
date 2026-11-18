"""Validated matching settings; intake owns the hard policy."""

import math
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MatchingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    eligibility_policy_version: str = Field(min_length=1)
    weights: dict[str, float]
    max_search_radius_m: float = Field(gt=0, le=100_000)
    offer_ttl_s: int = Field(gt=0, le=3600)
    fairness_window_days: int = Field(gt=0, le=365)
    slack_horizon_s: int = Field(gt=0, le=86_400)
    max_candidates: int = Field(gt=0, le=100)
    max_driver_routes: int = Field(gt=0, le=20)
    note: str

    @model_validator(mode="after")
    def valid_weights(self):
        if set(self.weights) != {"distance", "capacity", "fairness", "slack"}:
            raise ValueError("matching weights require distance, capacity, fairness and slack")
        if any(
            not math.isfinite(value) or value < 0 or value > 1 for value in self.weights.values()
        ):
            raise ValueError("matching weights must be in [0, 1]")
        if abs(sum(self.weights.values()) - 1) > 1e-9:
            raise ValueError("matching weights must sum to 1")
        return self


@lru_cache(maxsize=4)
def load_matching_config(path: str = "config/matching.json") -> MatchingConfig:
    return MatchingConfig.model_validate_json(Path(path).read_text())
