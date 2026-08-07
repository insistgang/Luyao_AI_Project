"""Build the static GitHub Pages shell for the embedded Gradio Space."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse


def space_url(space_id: str = "", explicit_url: str = "") -> str:
    explicit_url = explicit_url.strip().rstrip("/")
    if explicit_url:
        parsed = urlparse(explicit_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("HF_SPACE_URL 必须是有效的 HTTPS 地址。")
        if not parsed.hostname.endswith(".hf.space"):
            raise ValueError("HF_SPACE_URL 必须使用 huggingface.co 的 hf.space 域名。")
        return explicit_url

    space_id = space_id.strip().strip("/")
    if not space_id:
        return ""
    if space_id.count("/") != 1:
        raise ValueError("HF_SPACE_ID 必须采用 username/space-name 格式。")
    owner, name = space_id.split("/", 1)

    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    owner_slug, name_slug = slug(owner), slug(name)
    if not owner_slug or not name_slug:
        raise ValueError("HF_SPACE_ID 不能包含空的用户名或 Space 名称。")
    return f"https://{owner_slug}-{name_slug}.hf.space"


def build(
    source_dir: Path,
    output_dir: Path,
    *,
    space_id: str = "",
    explicit_url: str = "",
) -> str:
    resolved_url = space_url(space_id, explicit_url)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source_dir, output_dir)
    config = {"spaceUrl": resolved_url}
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
        space_id=os.getenv("HF_SPACE_ID", ""),
        explicit_url=os.getenv("HF_SPACE_URL", ""),
    )
    print(f"Pages artifact ready; Space URL: {url or 'not configured'}")


if __name__ == "__main__":
    main()
