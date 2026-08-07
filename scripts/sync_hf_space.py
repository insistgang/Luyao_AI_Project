"""Create/update the Hugging Face Docker Space without uploading local data."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

try:
    from .hf_identity import hf_space_url, resolve_space_id
except ImportError:
    from hf_identity import hf_space_url, resolve_space_id


APP_FILES = (
    "config.py",
    "guardrails.py",
    "main.py",
    "memory.py",
    "persona.py",
    "requirements.txt",
    "schemas.py",
    "service.py",
    "space_app.py",
    "space_launcher.py",
    "ui.py",
    "voice.py",
)

DEPLOYMENT_FILES = {
    "Dockerfile": "Dockerfile",
    "deploy/huggingface/README.md": "README.md",
}

SPACE_SETTING_NAMES = (
    "MINIMAX_API_KEY",
    "LUYAO_ACCESS_PASSWORD",
    "LUYAO_ACCESS_USER",
    "LUYAO_ALLOW_PUBLIC",
    "MINIMAX_API_HOST",
    "MINIMAX_CHAT_MODEL",
    "MINIMAX_VOICE_ID",
    "MINIMAX_SPEECH_MODEL",
    "MINIMAX_WHISPER_MODEL",
    "LUYAO_MEMORY_DB",
)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少必需配置：{name}")
    return value


def prepare_bundle(project_root: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative_path in APP_FILES:
        source = project_root / relative_path
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, output_dir / source.name)
    for source_name, target_name in DEPLOYMENT_FILES.items():
        source = project_root / source_name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, output_dir / target_name)


def _write_github_outputs(space_id: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"space_id={space_id}\n")
        output.write(f"space_url={hf_space_url(space_id)}\n")


def main() -> None:
    from huggingface_hub import HfApi

    token = required_env("HF_TOKEN")
    required_env("MINIMAX_API_KEY")
    if not os.getenv("LUYAO_ACCESS_PASSWORD", "").strip() and not os.getenv(
        "LUYAO_ALLOW_PUBLIC", ""
    ).strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "必须配置 LUYAO_ACCESS_PASSWORD；只有明确设置 "
            "LUYAO_ALLOW_PUBLIC=true 才能关闭访问保护。"
        )

    api = HfApi(token=token)
    space_id = resolve_space_id(
        api,
        explicit_space_id=os.getenv("HF_SPACE_ID", ""),
        space_name=os.getenv("HF_SPACE_NAME", "Luyao_AI_Project"),
    )
    api.create_repo(
        repo_id=space_id,
        repo_type="space",
        space_sdk="docker",
        private=False,
        exist_ok=True,
    )
    for name in SPACE_SETTING_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            api.add_space_secret(repo_id=space_id, key=name, value=value)

    project_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="luyao-space-") as temp_dir:
        bundle = Path(temp_dir)
        prepare_bundle(project_root, bundle)
        api.upload_folder(
            repo_id=space_id,
            repo_type="space",
            folder_path=bundle,
            commit_message="Deploy Luyao AI from GitHub Actions",
        )
    _write_github_outputs(space_id)
    print(f"Hugging Face Space synchronized: {space_id}")


if __name__ == "__main__":
    main()
