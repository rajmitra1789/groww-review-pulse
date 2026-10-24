"""Configuration sources used locally and on Streamlit Community Cloud."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from pulse.config import SETTING_NAMES, get_setting


@pytest.mark.parametrize("name", SETTING_NAMES)
def test_each_setting_falls_back_to_streamlit_secrets(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(secrets={name: f"streamlit-{name.lower()}"}),
    )

    assert get_setting(name) == f"streamlit-{name.lower()}"


@pytest.mark.parametrize("name", SETTING_NAMES)
def test_environment_takes_precedence_over_streamlit_secrets(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, f"environment-{name.lower()}")
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(secrets={name: f"streamlit-{name.lower()}"}),
    )

    assert get_setting(name) == f"environment-{name.lower()}"
