"""Check the private API and the authenticated UI without calling MiniMax."""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Mapping

from space_launcher import allow_unconfigured_preview, resolve_ui_port


def health_urls(environ: Mapping[str, str]) -> tuple[str, str]:
    api_port = int(environ.get("LUYAO_INTERNAL_API_PORT", "8000"))
    return (
        f"http://127.0.0.1:{api_port}/health",
        f"http://127.0.0.1:{resolve_ui_port(environ)}/",
    )


def check_health(environ: Mapping[str, str] | None = None) -> None:
    values = environ if environ is not None else os.environ
    backend_url, ui_url = health_urls(values)
    with urllib.request.urlopen(backend_url, timeout=3) as response:
        payload = json.load(response)
    configured = payload.get("config") or {}
    preview = (
        allow_unconfigured_preview(values)
        and payload.get("status") == "degraded"
        and not configured.get("llm_configured")
        and not configured.get("minimax_configured")
    )
    if payload.get("status") != "ok" and not preview:
        raise RuntimeError("backend is not ready")
    with urllib.request.urlopen(ui_url, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError("UI is not ready")


if __name__ == "__main__":
    check_health()
