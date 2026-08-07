"""Gradio client for the Luyao FastAPI backend."""

from __future__ import annotations

import asyncio
import inspect
import io
import json
import os
import re
import time
import wave
from typing import Any, AsyncIterator

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
) -> dict[str, Any]:
    return {
        "version": 1,
        "model_history": model_history[-40:],
        "display_history": display_history[-80:],
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


def _submission_key(message: str, history: list[dict[str, str]]) -> str:
    return json.dumps([message, history], ensure_ascii=False, sort_keys=True)


async def chat_with_backend(
    message: str,
    history: list[dict[str, Any]] | None,
    synthesize_voice: bool,
    conversation_state: dict[str, Any] | str | None = None,
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

    lock_key = _submission_key(text, prior_model)
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
            prior_model, base_display
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
                                prior_model, display
                            )
                            yield (
                                "",
                                display,
                                None,
                                "路遥正在一条条回复…",
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
                    next_model, display
                )
                status = f"完成 · {trace_id}" if trace_id else "完成"
                yield "", display, None, status, current_state
                return

            current_state = _new_conversation_state(
                next_model, base_display
            )
            yield (
                "",
                base_display,
                None,
                "正在生成一次完整语音…",
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
                    next_model, display
                )
                yield (
                    "",
                    display,
                    None,
                    f"文字已完成，语音生成失败：{exc}",
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
                    next_model, display
                )
                sync_status = (
                    f"同步播报 {index + 1}/{len(bubbles)}"
                    + (f" · {trace_id}" if trace_id else "")
                )
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
                next_model, display
            )
            status = f"完成 · {trace_id}" if trace_id else "完成"
            yield "", display, gr.skip(), status, current_state
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        display = [
            *base_display,
            {
                "role": "assistant",
                "content": (
                    f"[服务暂时不可用：HTTP "
                    f"{exc.response.status_code}]"
                ),
            },
        ]
        current_state = _new_conversation_state(
            prior_model, display
        )
        yield (
            text,
            display,
            None,
            f"后端错误：{detail}",
            current_state,
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        display = [
            *base_display,
            {"role": "assistant", "content": f"[生成遇到异常：{exc}]"},
        ]
        current_state = _new_conversation_state(
            prior_model, display
        )
        yield (
            text,
            display,
            None,
            f"处理异常：{exc}",
            current_state,
        )
    finally:
        _PROCESSING_LOCK.discard(lock_key)
        if completed:
            _RECENT_COMPLETIONS[lock_key] = time.monotonic()


async def backend_health() -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BACKEND_URL}/health")
            response.raise_for_status()
            payload = response.json()
        config = payload.get("config") or {}
        return (
            f"后端：{payload.get('status', 'unknown')} · "
            f"LLM：{'已配置' if config.get('llm_configured') else '未配置'} · "
            f"MiniMax：{'已配置' if config.get('minimax_configured') else '未配置'}"
        )
    except Exception as exc:
        return f"后端未连接：{exc}"


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="路遥 Luyao AI") as demo:
        initial_state = _new_conversation_state([], [])
        conversation_state = (
            gr.BrowserState(
                default_value=initial_state,
                storage_key="luyao_conversation_v1",
            )
            if hasattr(gr, "BrowserState")
            else gr.State(initial_state)
        )
        gr.Markdown(
            "# 路遥\n"
            "一台记得那些被时间放凉的小事的情感陪伴设备。"
        )
        status = gr.Markdown("后端状态尚未检查")
        with gr.Row():
            health_button = gr.Button("检查后端", size="sm")
            synthesize_voice = gr.Checkbox(
                label="生成 MiniMax 柔美语音", value=True
            )
        chatbot_options: dict[str, Any] = {
            "height": 520,
            "label": "对话",
        }
        chatbot_parameters = inspect.signature(gr.Chatbot).parameters
        if "type" in chatbot_parameters:
            chatbot_options["type"] = "messages"
        if "group_consecutive_messages" in chatbot_parameters:
            chatbot_options["group_consecutive_messages"] = False
        chatbot = gr.Chatbot(**chatbot_options)
        audio = gr.Audio(label="路遥的声音（自动播放）", autoplay=True)
        message = gr.Textbox(
            label="阿雾",
            placeholder="比如：我前女友后天要结婚了，我能送她什么？",
            lines=2,
        )
        with gr.Row():
            send = gr.Button("发送", variant="primary")
            gr.ClearButton(
                [message, chatbot, audio, conversation_state],
                value="清空",
            )

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
        ]
        event_options = {
            "fn": chat_with_backend,
            "inputs": inputs,
            "outputs": outputs,
            "concurrency_limit": 1,
            "concurrency_id": "luyao_chat",
        }
        send.click(**event_options)
        message.submit(**event_options)
        health_button.click(backend_health, outputs=status)
        demo.load(
            _restore_display,
            inputs=conversation_state,
            outputs=chatbot,
        )
    return demo


demo = build_demo()


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=8).launch(
        server_name=os.getenv("LUYAO_UI_HOST", "127.0.0.1"),
        server_port=int(os.getenv("LUYAO_UI_PORT", "7860")),
    )



