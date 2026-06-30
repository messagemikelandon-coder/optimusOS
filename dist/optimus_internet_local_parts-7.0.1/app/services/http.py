from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.security import validate_https_url


class SafeHttpClient:
    """Small outbound client restricted to explicitly approved HTTPS hosts."""

    def __init__(self, *, timeout_seconds: float, allowed_hosts: tuple[str, ...]) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)
        self._allowed_hosts = allowed_hosts

    async def get_json(self, url: str, params: Mapping[str, str | int | float] | None = None) -> Any:
        validate_https_url(url, self._allowed_hosts)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "Optimus-Landon-Motor-Works/7.0.1"},
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type:
                raise ValueError(f"Expected JSON response, received {content_type or 'unknown type'}")
            return response.json()
