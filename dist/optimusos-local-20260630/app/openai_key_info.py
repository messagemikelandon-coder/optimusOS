from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class KeyInfo:
    value: str
    source: str

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.value.encode("utf-8")).hexdigest()[:12]
        return f"sha256:{digest}"

    @property
    def masked(self) -> str:
        if len(self.value) <= 8:
            return "<too short>"
        return f"{self.value[:7]}...{self.value[-4:]}"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_project_key() -> KeyInfo:
    env_path = project_root() / ".env"
    values = dotenv_values(env_path)
    raw = values.get("OPENAI_API_KEY")
    key = raw.strip() if isinstance(raw, str) else ""
    if key:
        return KeyInfo(value=key, source=str(env_path))

    process_key = os.getenv("OPENAI_API_KEY", "").strip()
    if process_key:
        return KeyInfo(value=process_key, source="Windows/process environment")
    return KeyInfo(value="", source="not found")


def validate_key_text(key: str) -> list[str]:
    problems: list[str] = []
    if not key:
        problems.append("The API key is empty.")
        return problems
    lowered = key.lower()
    if lowered.startswith("bearer "):
        problems.append("Remove the word 'Bearer'; save only the API key.")
    if lowered.startswith("openai_api_key="):
        problems.append("Remove the duplicated OPENAI_API_KEY= prefix.")
    if any(char.isspace() for char in key):
        problems.append("The key contains whitespace or a line break.")
    if key in {"replace_me", "your_actual_openai_api_key"}:
        problems.append("The key is still an example placeholder.")
    return problems
