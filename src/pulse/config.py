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
RUNS_DIR = ROOT / "data" / "runs"

SETTING_NAMES = (
    "GROQ_API_KEY",
    "MCP_SERVER_URL",
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
