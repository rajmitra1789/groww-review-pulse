"""Defaults and secrets lookup (environment first, then Streamlit secrets)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS_DIR = ROOT / "data" / "snapshots"

load_dotenv(ROOT / ".env")

APP_ID = "com.nextbillion.groww"
PLAY_LANG = "en"
PLAY_COUNTRY = "in"
WINDOW_WEEKS = 12
TIMEZONE = "Asia/Kolkata"
MIN_WORDS = 9
MIN_ENGLISH_CONFIDENCE = 0.5
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
N_CLUSTERS = 5
MIN_CLUSTERABLE = 250
RANDOM_STATE = 42
KMEANS_N_INIT = 10
REPS_PER_THEME = 12
GROQ_MODEL = "openai/gpt-oss-120b"
QUOTE_WORDS = (9, 40)
MAX_NOTE_WORDS = 250
MIN_REVIEWS_FOR_PULSE = 30
# Hand check on week ending 2026-10-18. Complaint shares were
# 0.77, 0.58, 0.53, 0.48 and 0.47. 0.60 keeps the support cluster
# eligible; any empty top slots fill from the rest by review count.
MIN_COMPLAINT_SHARE = 0.60
RUNS_DIR = ROOT / "data" / "runs"

SETTING_NAMES = (
    "GROQ_API_KEY",
    "MCP_SERVER_URL",
    "MCP_AUTH_TOKEN",
    "PULSE_DOC_ID",
    "PULSE_RECIPIENT",
)


def get_setting(name: str) -> str:
    """Read a setting from the environment, then Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st

        secrets = st.secrets
        if name in secrets:
            return str(secrets[name])
    except Exception:
        pass
    return ""
