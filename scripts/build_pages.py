"""Build the static GitHub Pages shell for the hosted Gradio app."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse


def app_url(explicit_url: str = "") -> str:
    explicit_url = explicit_url.strip().rstrip("/")
    if not explicit_url:
        return ""
    parsed = urlparse(explicit_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("LUYAO_APP_URL 必须是有效的 HTTPS 地址。")
    if parsed.username or parsed.password:
        raise ValueError("LUYAO_APP_URL 不能包含账号或密码。")
    if parsed.query or parsed.fragment:
        raise ValueError("LUYAO_APP_URL 不能包含查询参数或片段。")
    return explicit_url


def build(
    source_dir: Path,
    output_dir: Path,
    *,
    explicit_url: str = "",
) -> str:
    resolved_url = app_url(explicit_url)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source_dir, output_dir)
    config = {"appUrl": resolved_url}
    config_script = (
        "window.LUYAO_CONFIG = Object.freeze("
        + json.dumps(config, ensure_ascii=False)
        + ");\n"
        + 'const luyaoHiddenStyle = document.createElement("style");\n'
        + 'luyaoHiddenStyle.textContent = ".open-link[hidden]'
        + '{display:none!important}";\n'
        + "document.head.append(luyaoHiddenStyle);\n"
    )
    (output_dir / "config.js").write_text(
        config_script,
        encoding="utf-8",
    )
    (output_dir / ".nojekyll").touch()
    return resolved_url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("site"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = build(
        args.source,
        args.output,
        explicit_url=os.getenv("LUYAO_APP_URL", ""),
    )
    print(f"Pages artifact ready; app URL: {url or 'not configured'}")


if __name__ == "__main__":
    main()
