"""Launch the private FastAPI core and public Gradio process in one Space."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path


SETTING_DEFAULTS = {
    "MINIMAX_API_HOST": "https://api.minimaxi.com",
    "MINIMAX_CHAT_MODEL": "abab6.5s-chat",
    "MINIMAX_VOICE_ID": "luyao_voice_v1",
    "MINIMAX_SPEECH_MODEL": "speech-2.8-hd",
    "MINIMAX_WHISPER_MODEL": "speech-2.6-hd",
}


def build_local_settings(environ: Mapping[str, str]) -> str:
    api_key = environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Hugging Face Space 缺少 MINIMAX_API_KEY Secret。")

    values = {"MINIMAX_API_KEY": api_key}
    values.update(
        {
            name: environ.get(name, default).strip() or default
            for name, default in SETTING_DEFAULTS.items()
        }
    )
    header = '"""Generated at container start from Hugging Face Secrets."""\n\n'
    body = "\n".join(
        f"{name} = {json.dumps(value, ensure_ascii=False)}"
        for name, value in values.items()
    )
    return f"{header}{body}\n"


def write_runtime_settings(
    target: Path, environ: Mapping[str, str] | None = None
) -> None:
    target.write_text(
        build_local_settings(environ or os.environ), encoding="utf-8"
    )
    target.chmod(0o600)


def wait_for_backend(process: subprocess.Popen[bytes], url: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"FastAPI 后端提前退出，退出码 {process.returncode}。"
            )
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    raise TimeoutError("FastAPI 后端在 60 秒内未就绪。")


def _terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    project_root = Path(__file__).resolve().parent
    write_runtime_settings(project_root / "local_settings.py")

    environment = os.environ.copy()
    api_port = int(environment.get("LUYAO_INTERNAL_API_PORT", "8000"))
    environment["LUYAO_API_URL"] = f"http://127.0.0.1:{api_port}"
    environment.setdefault("LUYAO_UI_HOST", "0.0.0.0")
    environment.setdefault("LUYAO_UI_PORT", "7860")

    backend: subprocess.Popen[bytes] | None = None
    frontend: subprocess.Popen[bytes] | None = None

    def stop_children(_signum=None, _frame=None) -> None:
        _terminate(frontend)
        _terminate(backend)

    signal.signal(signal.SIGTERM, stop_children)
    signal.signal(signal.SIGINT, stop_children)

    try:
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=project_root,
            env=environment,
        )
        wait_for_backend(backend, f"http://127.0.0.1:{api_port}/health")
        frontend = subprocess.Popen(
            [sys.executable, "space_app.py"],
            cwd=project_root,
            env=environment,
        )
        return frontend.wait()
    finally:
        stop_children()


if __name__ == "__main__":
    raise SystemExit(main())
