"""Resolve a Hugging Face Space identifier without exposing its token."""

from __future__ import annotations

import re
from typing import Any


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_part(value: str, label: str) -> str:
    value = value.strip()
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} 包含 Hugging Face 不支持的字符。")
    return value


def resolve_space_id(
    api: Any,
    explicit_space_id: str = "",
    space_name: str = "Luyao_AI_Project",
) -> str:
    explicit_space_id = explicit_space_id.strip().strip("/")
    if explicit_space_id:
        if explicit_space_id.count("/") != 1:
            raise ValueError("HF_SPACE_ID 必须采用 username/space-name 格式。")
        owner, name = explicit_space_id.split("/", 1)
        return f"{_validate_part(owner, 'HF 用户名')}/{_validate_part(name, 'Space 名称')}"

    identity = api.whoami()
    owner = str(identity.get("name", "")).strip()
    if not owner:
        raise RuntimeError("HF_TOKEN 有效，但无法识别 Hugging Face 用户名。")
    return (
        f"{_validate_part(owner, 'HF 用户名')}/"
        f"{_validate_part(space_name or 'Luyao_AI_Project', 'Space 名称')}"
    )


def hf_space_url(space_id: str) -> str:
    owner, name = space_id.split("/", 1)

    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    return f"https://{slug(owner)}-{slug(name)}.hf.space"
