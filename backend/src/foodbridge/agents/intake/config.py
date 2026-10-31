"""Load a versioned, validated policy once per process; domain functions remain file-independent."""

from functools import lru_cache
from pathlib import Path

from foodbridge.domain.intake import IntakePolicy


@lru_cache(maxsize=4)
def load_policy(path: str = "config/intake.json") -> IntakePolicy:
    return IntakePolicy.model_validate_json(Path(path).read_text())
