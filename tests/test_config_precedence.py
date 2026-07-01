from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def test_project_dotenv_key_wins_over_stale_windows_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "stale-windows-key")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=fresh-project-key\n", encoding="utf-8")

    settings = Settings()

    assert settings.openai_api_key == "fresh-project-key"


def test_model_names_are_normalized_from_dotenv_spacing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OPENAI_MODEL=gpt-4.1 mini\nOPENAI_FALLBACK_MODEL= gpt-4.1-mini \n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.openai_model == "gpt-4.1-mini"
    assert settings.openai_fallback_model == "gpt-4.1-mini"
