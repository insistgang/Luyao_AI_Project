"""Authenticated Gradio entry point for a managed container host."""

from __future__ import annotations

import os


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def build_auth(environ: dict[str, str] | os._Environ[str] | None = None):
    """Require a password on managed hosts unless public access is explicit."""

    values = environ if environ is not None else os.environ
    password = values.get("LUYAO_ACCESS_PASSWORD", "").strip()
    allow_public = _truthy(values.get("LUYAO_ALLOW_PUBLIC"))
    require_auth = _truthy(values.get("LUYAO_REQUIRE_AUTH")) or bool(
        values.get("SPACE_ID")
        or values.get("SPACE_HOST")
        or values.get("RENDER")
        or values.get("RENDER_SERVICE_ID")
    )

    if password:
        username = values.get("LUYAO_ACCESS_USER", "awu").strip() or "awu"
        return username, password
    if require_auth and not allow_public:
        raise RuntimeError(
            "托管服务缺少 LUYAO_ACCESS_PASSWORD；"
            "为防止公开消耗 MiniMax 额度，服务已拒绝启动。"
        )
    return None


def main() -> None:
    from ui import demo

    demo.queue(default_concurrency_limit=8).launch(
        server_name=os.getenv("LUYAO_UI_HOST", "0.0.0.0"),
        server_port=int(os.getenv("LUYAO_UI_PORT", "7860")),
        auth=build_auth(),
        auth_message="路遥只向受邀的人开放。请输入分享给你的访问账号与密码。",
        show_error=True,
    )


if __name__ == "__main__":
    main()
