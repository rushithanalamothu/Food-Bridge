"""Deterministic checks must not load a developer's live AI credentials.

Database tests still honor explicit environment URLs or the two local .env URLs.
Tests exercising dotenv resolution pass their own explicit _env_file fixture.
"""

import os

from dotenv import dotenv_values

from foodbridge.settings import Settings


def pytest_configure():
    local = dotenv_values(".env")
    for name in ("FOODBRIDGE_DATABASE_URL", "FOODBRIDGE_REDIS_URL"):
        if local.get(name):
            os.environ.setdefault(name, local[name])
    for name in list(os.environ):
        if name.startswith(("FOODBRIDGE_AI_", "FOODBRIDGE_EXTRACTION_")) or name in {
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "ANTHROPIC_API_KEY",
            "FOODBRIDGE_OPENAI_API_KEY",
            "FOODBRIDGE_GEMINI_API_KEY",
            "FOODBRIDGE_ANTHROPIC_API_KEY",
        }:
            os.environ.pop(name)
    Settings.model_config["env_file"] = None
