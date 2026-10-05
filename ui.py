"""Gradio client for the Luyao FastAPI backend."""

from __future__ import annotations

import asyncio
import html
import inspect
import io
import json
import logging
import os
import re
import secrets
import time
import wave
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import quote

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr
import httpx
import numpy as np


BACKEND_URL = os.getenv("LUYAO_API_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
BUBBLE_DELAY_SECONDS = max(
    0.0, float(os.getenv("LUYAO_BUBBLE_DELAY_MS", "180")) / 1000
)
_PROCESSING_LOCK: set[str] = set()
_RECENT_COMPLETIONS: dict[str, float] = {}
_DUPLICATE_WINDOW_SECONDS = 3.0
UI_ASSETS = Path(__file__).resolve().parent / "assets" / "ui"
UI_CSS = (UI_ASSETS / "luyao.css").read_text(encoding="utf-8")
UI_JS = (UI_ASSETS / "luyao.js").read_text(encoding="utf-8")
logger = logging.getLogger(__name__)


def _asset_url(filename: str) -> str:
    prefix = os.getenv("LUYAO_ROOT_PATH", "").rstrip("/")
    return f"{prefix}/gradio_api/file={quote(str(UI_ASSETS / filename))}"


def _connection_badge(state: str, label: str, detail: str = "", *, voice_ready: bool | None = None) -> str:
    capability = "" if voice_ready is None else f" data-voice-ready='{str(voice_ready).lower()}'"
    return (
        f"<span class='connection-badge' data-state='{state}'{capability} "
        f"title='{html.escape(detail, quote=True)}'>"
        f"<span class='connection-dot' aria-hidden='true'></span>"
        f"{html.escape(label)}</span>"
    )


def _activity(state: str, label: str) -> str:
    role = "alert" if state in {"error", "setup", "offline"} else "status"
    return f"<span class='activity-message' data-state='{state}' role='{role}'>{html.escape(label)}</span>"


def launch_options() -> dict[str, Any]:
    """Apply the same styling to local and hosted Gradio entry points."""
    options: dict[str, Any] = {
        "allowed_paths": [str(UI_ASSETS)],
        "favicon_path": str(UI_ASSETS / "luyao-avatar.png"),
        "blocked_paths": [
            str(Path(__file__).resolve().parent / name)
            for name in ["local_settings.py", ".env.ecs", "runtime-logs", "chroma_db"]
        ],
        "root_path": os.getenv("LUYAO_ROOT_PATH", "").rstrip("/"),
    }
    parameters = inspect.signature(gr.Blocks.launch).parameters
    if "css" in parameters:
        options["css"] = UI_CSS
        options["theme"] = _ui_theme()
    if "js" in parameters:
        options["js"] = UI_JS
    if "footer_links" in parameters:
        options["footer_links"] = []
    return options


def _ui_theme():
    return gr.themes.Soft(
        primary_hue="emerald",
        secondary_hue="rose",
        neutral_hue="gray",
        font=["PingFang SC", "Microsoft YaHei", "sans-serif"],
        radius_size="sm",
    )


def _browser_state_secret(target: Path | None = None) -> str:
    configured = os.getenv("LUYAO_BROWSER_STATE_SECRET", "").strip()
    if configured:
        return configured
    target = target or Path(__file__).resolve().parent / "runtime-logs" / "browser-state.key"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as secret_file:
            secret_file.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    target.chmod(0o600)
    return target.read_text(encoding="utf-8").strip()


def _display_text(text: str) -> str:
    text = re.sub(
        r"\[(?:whisper|sigh)\]\s*", "", text, flags=re.IGNORECASE
    )
    return re.sub(
        r"\[pause\]", "\n", text, flags=re.IGNORECASE
    ).strip()


def _clean_history(
    history: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Convert multiple visual bubbles back into compact model history."""

    cleaned: list[dict[str, str]] = []
    for item in history or []:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        clean_text = re.sub(r"<[^>]+>", "", content).strip()
        if not clean_text:
            continue
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] += f"\n{clean_text}"
        else:
            cleaned.append({"role": role, "content": clean_text})
    return cleaned[-40:]



def _display_history(
    history: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Preserve visual bubbles exactly instead of merging adjacent roles."""

    display: list[dict[str, str]] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        text = content.strip()
        if text:
            display.append({"role": role, "content": text})
    return display[-80:]


def _new_conversation_state(
    model_history: list[dict[str, str]],
    display_history: list[dict[str, str]],
    *, pending_turn: bool = False, model_complete: bool = False,
) -> dict[str, Any]:
    return {
        "version": 1,
        "model_history": model_history[-40:],
        "display_history": display_history[-80:],
        "pending_turn": pending_turn,
        "model_complete": model_complete,
    }


def _state_histories(
    state: dict[str, Any] | str | None,
    live_history: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if isinstance(state, str):
        try:
            decoded = json.loads(state)
        except json.JSONDecodeError:
            decoded = None
        state = decoded if isinstance(decoded, dict) else None

    live_display = _display_history(live_history)
    if isinstance(state, dict) and state.get("version") == 1:
        model_history = _clean_history(state.get("model_history"))
        saved_display = _display_history(state.get("display_history"))
        return model_history, live_display or saved_display

    return _clean_history(live_display), live_display


def _restore_display(state: dict[str, Any] | str | None) -> list[dict[str, str]]:
    return _state_histories(state, None)[1]


def _audio_sync_delays(
    bubbles: list[str],
    audio_value: tuple[int, np.ndarray],
) -> list[float]:
    """Allocate the measured WAV duration across visible reply bubbles."""

    if not bubbles:
        return []
    sample_rate, samples = audio_value
    total_seconds = (
        len(samples) / sample_rate if sample_rate > 0 else 0.0
    )
    weights: list[float] = []
    for bubble in bubbles:
        spoken = len(re.findall(r"[\w\u4e00-\u9fff]", bubble))
        punctuation = len(re.findall(r"[，、；：。！？,.!?…]", bubble))
        weights.append(max(1.0, spoken + punctuation * 1.6))
    total_weight = sum(weights)
    return [
        total_seconds * weight / total_weight
        for weight in weights
    ]

def _wav_for_gradio(audio: bytes) -> tuple[int, np.ndarray]:
    with wave.open(io.BytesIO(audio), "rb") as wav_file:
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise ValueError("后端返回了不受支持的 WAV 格式")
        sample_rate = wav_file.getframerate()
        samples = np.frombuffer(
            wav_file.readframes(wav_file.getnframes()), dtype="<i2"
        )
    return sample_rate, samples.copy()


async def _iter_sse(
    response: httpx.Response,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    event_name = "message"
    async for raw_line in response.aiter_lines():
        line = raw_line.strip()
        if not line:
            event_name = "message"
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield event_name, payload


def _split_block(block: str, max_chars: int) -> list[str]:
    fragments = re.findall(r".+?(?:[。！？!?…；;]+|$)", block)
    bubbles: list[str] = []
    current = ""
    for fragment in fragments:
        fragment = fragment.strip()
        if not fragment:
            continue
        if current and len(current) + len(fragment) > max_chars:
            bubbles.append(current)
            current = fragment
        else:
            current += fragment
    if current:
        bubbles.append(current)
    return bubbles


def _split_into_bubbles(text: str, max_chars: int = 22) -> list[str]:
    """Split a reply; pause tags and model newlines are hard boundaries."""

    raw = _display_text(text)
    if not raw:
        return []
    bubbles: list[str] = []
    for block in raw.splitlines():
        block = block.strip()
        if not block:
            continue
        bubbles.extend(_split_block(block, max_chars))
    return bubbles


def _submission_key(message: str, history: list[dict[str, str]], session_id: str | None = None) -> str:
    return json.dumps([session_id, message, history], ensure_ascii=False, sort_keys=True)


async def chat_with_backend(
    message: str,
    history: list[dict[str, Any]] | None,
    synthesize_voice: bool,
    conversation_state: dict[str, Any] | str | None = None,
    session_id: str | None = None,
) -> AsyncIterator[
    tuple[
        str,
        list[dict[str, str]],
        Any,
        str,
        dict[str, Any],
    ]
]:
    text = (message or "").strip()
    prior_model, prior_display = _state_histories(
        conversation_state, history
    )
    current_state = _new_conversation_state(
        prior_model, prior_display
    )
    if not text:
        yield "", prior_display, None, "请输入一段话。", current_state
        return

    lock_key = _submission_key(text, prior_model, session_id)
    now = time.monotonic()
    stale_before = now - 30.0
    for key, completed_at in tuple(_RECENT_COMPLETIONS.items()):
        if completed_at < stale_before:
            _RECENT_COMPLETIONS.pop(key, None)
    if (
        lock_key in _PROCESSING_LOCK
        or now - _RECENT_COMPLETIONS.get(lock_key, 0.0)
        < _DUPLICATE_WINDOW_SECONDS
    ):
        return
    _PROCESSING_LOCK.add(lock_key)

    completed = False
    base_display = [
        *prior_display,
        {"role": "user", "content": text},
    ]
    display = list(base_display)
    assistant_text = ""
    trace_id = ""
    next_model = list(prior_model)
    try:
        current_state = _new_conversation_state(
            prior_model, base_display, pending_turn=True
        )
        yield "", display, None, "路遥正在思考…", current_state
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{BACKEND_URL}/api/chat/stream",
                json={
                    "user_id": "awu_001",
                    "user_message": text,
                    "chat_history": prior_model[-20:],
                },
            ) as response:
                response.raise_for_status()
                async for event, payload in _iter_sse(response):
                    if event == "meta":
                        trace_id = str(payload.get("trace_id") or "")
                    elif event == "text_delta":
                        assistant_text += str(payload.get("text") or "")
                        if not synthesize_voice:
                            bubbles = _split_into_bubbles(assistant_text)
                            display = [
                                *base_display,
                                *(
                                    {
                                        "role": "assistant",
                                        "content": bubble,
                                    }
                                    for bubble in bubbles
                                ),
                            ]
                            current_state = _new_conversation_state(
                                prior_model, display, pending_turn=True
                            )
                            yield (
                                "",
                                display,
                                None,
                                "正在回复…",
                                current_state,
                            )
                            if BUBBLE_DELAY_SECONDS:
                                await asyncio.sleep(BUBBLE_DELAY_SECONDS)
                    elif event == "done":
                        completed = True
                        trace_id = str(
                            payload.get("trace_id") or trace_id
                        )
                    elif event == "error":
                        raise RuntimeError(
                            str(
                                payload.get("message")
                                or "对话流返回错误"
                            )
                        )

            if not completed or not assistant_text:
                raise RuntimeError("对话流在完成前中断")

            bubbles = _split_into_bubbles(assistant_text)
            if not bubbles:
                raise RuntimeError("回复中没有可显示文本")
            next_model = [
                *prior_model,
                {"role": "user", "content": text},
                {"role": "assistant", "content": assistant_text},
            ][-40:]

            if not synthesize_voice:
                display = [
                    *base_display,
                    *(
                        {"role": "assistant", "content": bubble}
                        for bubble in bubbles
                    ),
                ]
                current_state = _new_conversation_state(
                    next_model, display, pending_turn=True, model_complete=True
                )
                status = "路遥说完了。"
                yield "", display, None, status, current_state
                return

            current_state = _new_conversation_state(
                next_model, base_display, pending_turn=True, model_complete=True
            )
            yield (
                "",
                base_display,
                None,
                "正在准备语音…",
                current_state,
            )
            try:
                voice_response = await client.post(
                    f"{BACKEND_URL}/api/voice",
                    json={"text": assistant_text},
                )
                voice_response.raise_for_status()
                audio_value = _wav_for_gradio(
                    voice_response.content
                )
            except (httpx.HTTPError, ValueError) as exc:
                display = [
                    *base_display,
                    *(
                        {"role": "assistant", "content": bubble}
                        for bubble in bubbles
                    ),
                ]
                current_state = _new_conversation_state(
                    next_model, display, pending_turn=True, model_complete=True
                )
                yield (
                    "",
                    display,
                    None,
                    "文字已送达，声音暂时没有连上。",
                    current_state,
                )
                return

            delays = _audio_sync_delays(bubbles, audio_value)
            display = list(base_display)
            for index, bubble in enumerate(bubbles):
                if index:
                    delay = delays[index - 1]
                    if index == 1:
                        delay += 0.20
                    if delay > 0:
                        await asyncio.sleep(delay)
                display = [
                    *display,
                    {"role": "assistant", "content": bubble},
                ]
                audio_update = (
                    audio_value if index == 0 else gr.skip()
                )
                current_state = _new_conversation_state(
                    next_model, display, pending_turn=True, model_complete=True
                )
                sync_status = "路遥正在轻声说。"
                yield (
                    "",
                    display,
                    audio_update,
                    sync_status,
                    current_state,
                )

            if delays and delays[-1] > 0:
                await asyncio.sleep(delays[-1])
            current_state = _new_conversation_state(
                next_model, display, pending_turn=True, model_complete=True
            )
            status = "路遥说完了。"
            yield "", display, gr.skip(), status, current_state
    except httpx.HTTPStatusError as exc:
        logger.warning("chat request failed: HTTP %s", exc.response.status_code)
        display = prior_display
        current_state = _new_conversation_state(
            prior_model, display
        )
        yield (
            text,
            display,
            None,
            "连接暂时中断。",
            current_state,
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.warning("chat failed: %s", type(exc).__name__)
        display = prior_display
        current_state = _new_conversation_state(
            prior_model, display
        )
        yield (
            text,
            display,
            None,
            "对话暂时不可用。",
            current_state,
        )
    finally:
        _PROCESSING_LOCK.discard(lock_key)
        if completed:
            _RECENT_COMPLETIONS[lock_key] = time.monotonic()


async def _read_service_health() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{BACKEND_URL}/health")
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("config"), dict) or payload.get("status") not in {"ok", "degraded"}:
        raise ValueError("Invalid service health response")
    return payload


def _service_state(payload: dict[str, Any]) -> tuple[str, str, bool]:
    config = payload["config"]
    if not config.get("llm_configured"):
        return "setup", "聊天服务尚未配置，消息未发送。", False
    voice_ready = bool(config.get("minimax_configured"))
    if payload.get("status") != "ok" and voice_ready:
        return "ready", "部分服务异常。", voice_ready
    return "ready", "" if voice_ready else "语音服务尚未配置。", voice_ready


def _health_badge(state: str, detail: str, voice_ready: bool) -> str:
    label = {"setup": "聊天未配置", "offline": "服务未连接", "ready": "已连接" if voice_ready else "文字已连接"}[state]
    if state == "ready" and detail == "部分服务异常。":
        state, label = "setup", "连接受限"
    return _connection_badge(state, label, detail or "路遥已准备好", voice_ready=voice_ready)


async def backend_health() -> str:
    try:
        return _health_badge(*_service_state(await _read_service_health()))
    except Exception as exc:
        logger.info("backend health unavailable: %s", type(exc).__name__)
        return _health_badge("offline", "暂时无法连接对话服务", False)


def _voice_ready(state: dict[str, Any] | str | None) -> bool:
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except ValueError:
            return False
    return bool(isinstance(state, dict) and state.get("voice_ready"))


def _idle_controls(voice_ready: bool | None = None):
    voice = gr.update(value=False) if voice_ready is False else gr.skip()
    return gr.update(visible=True, interactive=True), gr.update(visible=False), voice


async def submit_message(message, history, synthesize_voice, conversation_state=None, request: gr.Request = None):
    text = (message or "").strip()
    model, display = _state_histories(conversation_state, history)
    stored = {**_new_conversation_state(model, display), "voice_ready": _voice_ready(conversation_state)}
    if not text:
        yield gr.update(value="", interactive=True), display, None, _activity("idle", ""), stored, *_idle_controls(), gr.skip()
        return
    yield gr.update(interactive=False), display, None, _activity("busy", "正在检查服务…"), stored, gr.update(visible=False), gr.update(visible=True), gr.skip(), gr.skip()
    try:
        state, detail, voice_ready = _service_state(await _read_service_health())
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("submission preflight failed: %s", type(exc).__name__)
        state, detail, voice_ready = "offline", "无法连接服务，消息未发送。", False
    stored["voice_ready"] = voice_ready
    if state != "ready":
        yield gr.update(value=message, interactive=True), display, None, _activity("error", detail), stored, *_idle_controls(voice_ready), _health_badge(state, detail, voice_ready)
        return
    generator = chat_with_backend(text, history, synthesize_voice and voice_ready, stored, getattr(request, "session_hash", None))
    last = None
    try:
        async for output in generator:
            last = output
            next_state = {**output[4], "voice_ready": voice_ready}
            yield output[0], output[1], output[2], _activity("busy", output[3]), next_state, gr.skip(), gr.skip(), gr.skip(), _health_badge(state, detail, voice_ready)
    finally:
        await generator.aclose()
    if last is None:
        last = (message, display, None, "", stored)
    failed = bool(last[0])
    activity = _activity("error", "回复失败，输入已保留。") if failed else _activity("ready", "" if voice_ready else "语音服务尚未配置。")
    if not failed and ("语音生成失败" in last[3] or "声音暂时没有连上" in last[3]):
        activity = _activity("setup", "文字已返回，语音暂不可用。")
    badge = _health_badge("offline", "回复失败", False) if failed else _health_badge(state, detail, voice_ready)
    yield gr.update(interactive=True), gr.skip(), gr.skip(), activity, {**last[4], "voice_ready": voice_ready}, *_idle_controls(voice_ready), badge


def stop_submission(message, history, conversation_state=None):
    model, display = _state_histories(conversation_state, history)
    draft = message or ""
    state = conversation_state
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except ValueError:
            state = {}
    if isinstance(state, dict) and state.get("pending_turn") and display:
        last_user = max((index for index, item in enumerate(display) if item["role"] == "user"), default=-1)
        if last_user >= 0:
            if state.get("model_complete") and model and model[-1]["role"] == "assistant":
                display = [*display[:last_user + 1], *({"role": "assistant", "content": text} for text in _split_into_bubbles(model[-1]["content"]))]
            elif last_user == len(display) - 1:
                draft = draft or display.pop()["content"]
            else:
                model = [*model, *_clean_history(display[last_user:])]
    voice_ready = _voice_ready(conversation_state)
    stored = {**_new_conversation_state(model, display), "voice_ready": voice_ready}
    return gr.update(value=draft, interactive=True), display, None, _activity("idle", "已停止回复。"), stored, *_idle_controls(), gr.skip()


def reset_conversation():
    return "", [], None, "新的对话，慢慢开始。", _new_conversation_state([], [])


def reset_ui_conversation(conversation_state=None):
    voice_ready = _voice_ready(conversation_state)
    stored = {**_new_conversation_state([], []), "voice_ready": voice_ready}
    return gr.update(value="", interactive=True), [], None, _activity("idle", ""), stored, *_idle_controls(), gr.skip()


def build_demo() -> gr.Blocks:
    block_options: dict[str, Any] = {
        "title": "路遥 · 此刻，听你说",
        "fill_width": True,
        "fill_height": True,
    }
    if "css" in inspect.signature(gr.Blocks).parameters:
        block_options.update(css=UI_CSS, theme=_ui_theme())
    if "js" in inspect.signature(gr.Blocks).parameters:
        block_options["js"] = UI_JS
    avatar = _asset_url("luyao-avatar.png")
    with gr.Blocks(**block_options) as demo:
        initial_state = _new_conversation_state([], [])
        conversation_state = (
            gr.BrowserState(
                default_value=initial_state,
                storage_key="luyao_conversation_v2",
                secret=_browser_state_secret(),
            )
            if hasattr(gr, "BrowserState")
            else gr.State(initial_state)
        )
        with gr.Row(elem_id="luyao-shell", equal_height=True):
            with gr.Column(scale=0, min_width=240, elem_id="luyao-sidebar"):
                gr.HTML(
                    "<div class='luyao-brand'><span class='brand-name'>路遥</span>"
                    "<span class='brand-caption'>此刻，听你说。</span></div>",
                    elem_id="luyao-brand",
                )
                new_chat = gr.Button(
                    "新对话", icon=str(UI_ASSETS / "icons" / "plus.svg"),
                    elem_id="luyao-new-chat", size="sm",
                )
                gr.HTML(
                    f"<div class='sidebar-portrait'><img src='{avatar}' alt='路遥的插画头像'>"
                    "<p>不着急。<br>我们慢慢聊。</p></div>",
                    elem_id="luyao-portrait",
                )
                with gr.Accordion("路遥的声音", open=False, elem_id="luyao-player"):
                    audio_options: dict[str, Any] = {
                        "label": "语音播放", "show_label": False,
                        "autoplay": True, "interactive": False,
                        "elem_id": "luyao-audio", "container": False,
                    }
                    if "buttons" in inspect.signature(gr.Audio).parameters:
                        audio_options["buttons"] = []
                    audio = gr.Audio(**audio_options)
                gr.HTML(
                    "<div class='sidebar-user'><span class='user-avatar'>雾</span>"
                    "<div><b>阿雾</b><span>此刻的对话</span></div></div>",
                    elem_id="luyao-user",
                )
            with gr.Column(scale=1, min_width=0, elem_id="luyao-main"):
                with gr.Row(elem_id="luyao-header"):
                    gr.HTML(
                        f"<div class='conversation-heading'><img src='{avatar}' alt=''>"
                        "<div><h1>与你的对话</h1><p>今天，也在这里。</p></div></div>",
                        elem_id="luyao-heading",
                    )
                    connection = gr.HTML(
                        _connection_badge("checking", "正在连接"),
                        elem_id="luyao-connection",
                    )
                    health_button = gr.Button(
                        "刷新", icon=str(UI_ASSETS / "icons" / "refresh-cw.svg"),
                        elem_id="luyao-refresh", size="sm", scale=0, min_width=64,
                    )
                chatbot_options: dict[str, Any] = {
                    "height": 520, "label": "与路遥的对话", "show_label": False,
                    "container": False, "layout": "bubble", "min_width": 0,
                    "elem_id": "luyao-chat",
                    "avatar_images": (None, str(UI_ASSETS / "luyao-avatar.png")),
                    "placeholder": (
                        f"<div class='chat-welcome'><img src='{avatar}' alt=''>"
                        "<span class='welcome-eyebrow'>路遥，在听</span>"
                        "<h2>阿雾，今天过得怎么样？</h2>"
                        "<p>开心的、难过的，或只是一些小事。<br>我在，慢慢说。</p></div>"
                    ),
                }
                chatbot_parameters = inspect.signature(gr.Chatbot).parameters
                if "type" in chatbot_parameters:
                    chatbot_options["type"] = "messages"
                if "group_consecutive_messages" in chatbot_parameters:
                    chatbot_options["group_consecutive_messages"] = False
                if "buttons" in chatbot_parameters:
                    chatbot_options["buttons"] = ["copy"]
                chatbot = gr.Chatbot(**chatbot_options)
                with gr.Row(elem_id="luyao-starters"):
                    starters = [
                        (gr.Button(prompt, size="sm", elem_classes="starter-prompt"), prompt)
                        for prompt in ["今天有点累。", "还记得那杯奶茶吗？", "想和你聊一聊。"]
                    ]
                with gr.Column(min_width=0, elem_id="luyao-composer"):
                    with gr.Row(elem_id="luyao-input-row"):
                        message = gr.Textbox(
                            label="消息", show_label=False, container=False,
                            placeholder="此刻的心情…", lines=2, max_lines=5,
                            elem_id="luyao-message", scale=1, min_width=0,
                        )
                        with gr.Row(elem_id="luyao-submit-controls"):
                            send = gr.Button(
                                "发送", variant="primary", size="sm",
                                icon=str(UI_ASSETS / "icons" / "send.svg"),
                                elem_id="luyao-send", scale=0, min_width=48,
                            )
                            stop = gr.Button(
                                "停止", size="sm", visible=False,
                                icon=str(UI_ASSETS / "icons" / "square.svg"),
                                elem_id="luyao-stop", scale=0, min_width=48,
                            )
                    with gr.Row(elem_id="luyao-composer-footer"):
                        synthesize_voice = gr.Checkbox(
                            label="语音回复", value=True, container=False,
                            elem_id="luyao-voice-toggle", scale=0, min_width=110,
                        )
                        status = gr.HTML(_activity("checking", ""), elem_id="luyao-activity")

        inputs = [
            message,
            chatbot,
            synthesize_voice,
            conversation_state,
        ]
        outputs = [
            message,
            chatbot,
            audio,
            status,
            conversation_state,
            send,
            stop,
            synthesize_voice,
            connection,
        ]
        event_options = {
            "fn": submit_message,
            "inputs": inputs,
            "outputs": outputs,
            "concurrency_limit": 1,
            "concurrency_id": "luyao_chat",
            "show_progress": "hidden",
            "trigger_mode": "once",
        }
        send_event = send.click(**event_options)
        submit_event = message.submit(**event_options)
        new_chat.click(
            reset_ui_conversation, inputs=conversation_state, outputs=outputs, queue=False, show_progress="hidden",
            cancels=[send_event, submit_event],
        ).then(fn=None, inputs=None, outputs=None, queue=False, js="() => {window.__luyaoUi?.sync(); document.querySelector('#luyao-message textarea')?.focus(); return [];}")
        chatbot.clear(
            reset_ui_conversation, inputs=conversation_state, outputs=outputs, queue=False, show_progress="hidden",
            cancels=[send_event, submit_event],
        )
        stop.click(
            stop_submission, inputs=[message, chatbot, conversation_state], outputs=outputs,
            queue=False, show_progress="hidden", cancels=[send_event, submit_event],
        )
        for starter, prompt in starters:
            starter.click(
                lambda value=prompt: value, outputs=message,
                queue=False, show_progress="hidden",
            ).then(fn=None, inputs=None, outputs=None, queue=False, js="() => {window.__luyaoUi?.sync(); document.querySelector('#luyao-message textarea')?.focus(); return [];}")
        health_button.click(
            backend_health, outputs=connection, queue=False, show_progress="hidden",
        )
        demo.load(
            backend_health, outputs=connection, show_progress="hidden",
        )
        demo.load(
            _restore_display,
            inputs=conversation_state,
            outputs=chatbot,
            show_progress="hidden",
        )
    return demo


demo = build_demo()


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=8).launch(
        server_name=os.getenv("LUYAO_UI_HOST", "127.0.0.1"),
        server_port=int(os.getenv("LUYAO_UI_PORT", "7860")),
        **launch_options(),
    )
