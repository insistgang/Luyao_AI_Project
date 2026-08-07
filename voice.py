"""MiniMax voice cloning and single-request emotion-aware PCM renderer."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import shutil
import subprocess
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

from config import AppSettings


class VoiceRenderError(RuntimeError):
    pass


class VoiceStyle(StrEnum):
    DEFAULT = "default"
    WHISPER = "whisper"
    SIGH = "sigh"


@dataclass(slots=True)
class VoiceSegment:
    text: str
    style: VoiceStyle = VoiceStyle.DEFAULT
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    sigh_prefix: bool = False


class EmotionTagParser:
    TAG_PATTERN = re.compile(
        r"(\[(?:whisper|sigh|pause)\])", re.IGNORECASE
    )

    def __init__(self, pause_ms: int = 400) -> None:
        self.pause_ms = pause_ms

    def parse(self, raw_text: str) -> list[VoiceSegment]:
        pieces = self.TAG_PATTERN.split(raw_text)
        style = VoiceStyle.DEFAULT
        pending_pause = 0
        pending_sigh = False
        segments: list[VoiceSegment] = []

        for piece in pieces:
            if not piece:
                continue
            if self.TAG_PATTERN.fullmatch(piece):
                tag = piece.lower()
                if tag == "[pause]":
                    if segments:
                        segments[-1].pause_after_ms += self.pause_ms
                    else:
                        pending_pause += self.pause_ms
                elif tag == "[whisper]":
                    style = VoiceStyle.WHISPER
                    pending_sigh = False
                elif tag == "[sigh]":
                    style = VoiceStyle.SIGH
                    pending_sigh = True
                continue

            text = re.sub(r"\s+", " ", piece).strip()
            if not text:
                continue
            segments.append(
                VoiceSegment(
                    text=text,
                    style=style,
                    pause_before_ms=pending_pause,
                    sigh_prefix=pending_sigh,
                )
            )
            pending_pause = 0
            pending_sigh = False

        if pending_pause and segments:
            segments[-1].pause_after_ms += pending_pause
        return segments


class VoiceRenderAgent:
    """Render one assistant reply with exactly one MiniMax TTS request."""

    _VOICE_ID_PATTERN = re.compile(
        r"^[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]$"
    )

    def __init__(
        self,
        settings: AppSettings,
        *,
        client: httpx.AsyncClient | None = None,
        parser: EmotionTagParser | None = None,
    ) -> None:
        self.settings = settings
        self.parser = parser or EmotionTagParser()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.minimax_timeout_seconds)
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _require_api_key(self) -> str:
        if not self.settings.minimax_api_key:
            raise VoiceRenderError("MINIMAX_API_KEY is not configured")
        return self.settings.minimax_api_key

    def _voice_setting(
        self, segment: VoiceSegment, voice_id: str
    ) -> tuple[str, dict[str, Any], str]:
        text = segment.text
        if segment.style == VoiceStyle.WHISPER:
            return (
                self.settings.minimax_whisper_model,
                {
                    "voice_id": voice_id,
                    "speed": 0.88,
                    "vol": 0.85,
                    "pitch": 1,
                    "emotion": "whisper",
                },
                text,
            )
        if segment.style == VoiceStyle.SIGH:
            if segment.sigh_prefix:
                text = f"(sighs) {text}"
            return (
                self.settings.minimax_model,
                {
                    "voice_id": voice_id,
                    "speed": 0.90,
                    "vol": 0.90,
                    "pitch": 1,
                    "emotion": "sad",
                },
                text,
            )
        return (
            self.settings.minimax_model,
            {
                "voice_id": voice_id,
                "speed": 0.94,
                "vol": 1.0,
                "pitch": 0,
            },
            text,
        )

    def _single_request_segment(self, raw_text: str) -> VoiceSegment:
        """Collapse tagged phrases into one TTS request to avoid double billing."""

        segments = self.parser.parse(raw_text)
        if not segments:
            raise VoiceRenderError("No speakable text after parsing emotion tags")

        primary_style = next(
            (
                segment.style
                for segment in segments
                if segment.style != VoiceStyle.DEFAULT
            ),
            VoiceStyle.DEFAULT,
        )
        parts: list[str] = []
        for segment in segments:
            if segment.pause_before_ms:
                seconds = segment.pause_before_ms / 1000
                parts.append(f"<#{seconds:.2f}#>")
            if segment.sigh_prefix:
                parts.append("(sighs)")
            parts.append(segment.text)
            if segment.pause_after_ms:
                seconds = segment.pause_after_ms / 1000
                parts.append(f"<#{seconds:.2f}#>")

        return VoiceSegment(
            text=" ".join(parts),
            style=primary_style,
            sigh_prefix=False,
        )

    async def stream_pcm(
        self, raw_text: str, *, voice_id: str | None = None
    ) -> AsyncIterator[bytes]:
        selected_voice = voice_id or self.settings.minimax_voice_id
        segment = self._single_request_segment(raw_text)
        async for chunk in self._stream_segment(segment, selected_voice):
            yield chunk

    async def render_wav(
        self, raw_text: str, *, voice_id: str | None = None
    ) -> bytes:
        pcm = bytearray()
        async for chunk in self.stream_pcm(raw_text, voice_id=voice_id):
            pcm.extend(chunk)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.settings.audio_sample_rate)
            wav_file.writeframes(bytes(pcm))
        return output.getvalue()

    async def _stream_segment(
        self, segment: VoiceSegment, voice_id: str
    ) -> AsyncIterator[bytes]:
        api_key = self._require_api_key()
        model, voice_setting, text = self._voice_setting(segment, voice_id)
        payload = {
            "model": model,
            "text": text,
            "stream": False,
            "voice_setting": voice_setting,
            "audio_setting": {
                "sample_rate": self.settings.audio_sample_rate,
                "bitrate": self.settings.audio_bitrate,
                "format": "pcm",
                "channel": 1,
            },
            "language_boost": "Chinese",
            "subtitle_enable": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = await self._client.post(
            f"{self.settings.minimax_api_host}/v1/t2a_v2",
            headers=headers,
            json=payload,
        )
        if response.status_code >= 400:
            raise VoiceRenderError(
                f"MiniMax TTS returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise VoiceRenderError("MiniMax TTS returned invalid JSON") from exc
        base = data.get("base_resp") or {}
        if base.get("status_code") not in (None, 0):
            raise VoiceRenderError(
                f"MiniMax TTS error {base.get('status_code')}: "
                f"{base.get('status_msg', 'unknown error')}"
            )
        audio_hex = (data.get("data") or {}).get("audio")
        if not audio_hex:
            raise VoiceRenderError("MiniMax returned no audio data")
        try:
            audio = bytes.fromhex(audio_hex)
        except ValueError as exc:
            raise VoiceRenderError(
                "MiniMax returned invalid hex audio"
            ) from exc
        if audio:
            yield audio

    async def upload_audio(self, audio_path: Path, purpose: str) -> int:
        api_key = self._require_api_key()
        path = audio_path.resolve()
        if not path.is_file():
            raise VoiceRenderError(f"Audio file not found: {path}")
        if path.suffix.lower() not in {".mp3", ".m4a", ".wav"}:
            raise VoiceRenderError("Clone audio must be mp3, m4a, or wav")
        if path.stat().st_size > 20 * 1024 * 1024:
            raise VoiceRenderError("Clone audio must be no larger than 20 MB")
        with path.open("rb") as source:
            response = await self._client.post(
                f"{self.settings.minimax_api_host}/v1/files/upload",
                headers={"Authorization": f"Bearer {api_key}"},
                data={"purpose": purpose},
                files={
                    "file": (
                        path.name,
                        source,
                        "application/octet-stream",
                    )
                },
            )
        self._raise_for_minimax(response, "file upload")
        file_id = (response.json().get("file") or {}).get("file_id")
        if file_id is None:
            raise VoiceRenderError(
                "MiniMax upload response did not include file_id"
            )
        return int(file_id)

    async def clone_voice(
        self,
        clone_audio: Path,
        voice_id: str,
        *,
        prompt_audio: Path | None = None,
        prompt_text: str | None = None,
        preview_text: str | None = None,
        noise_reduction: bool = True,
        volume_normalization: bool = True,
    ) -> dict[str, Any]:
        if not self._VOICE_ID_PATTERN.fullmatch(voice_id):
            raise VoiceRenderError(
                "voice_id must be 8-256 characters, start with a letter, "
                "use letters/digits/-/_, and end with a letter or digit"
            )
        if (prompt_audio is None) != (prompt_text is None):
            raise VoiceRenderError(
                "prompt_audio and prompt_text must be provided together"
            )

        clone_file_id = await self.upload_audio(
            clone_audio, "voice_clone"
        )
        payload: dict[str, Any] = {
            "file_id": clone_file_id,
            "voice_id": voice_id,
            "model": self.settings.minimax_model,
            "need_noise_reduction": noise_reduction,
            "need_volume_normalization": volume_normalization,
            "aigc_watermark": False,
        }
        if prompt_audio is not None and prompt_text is not None:
            prompt_file_id = await self.upload_audio(
                prompt_audio, "prompt_audio"
            )
            payload["clone_prompt"] = {
                "prompt_audio": prompt_file_id,
                "prompt_text": prompt_text,
            }
        if preview_text:
            payload["text"] = preview_text[:1000]

        response = await self._client.post(
            f"{self.settings.minimax_api_host}/v1/voice_clone",
            headers={
                "Authorization": f"Bearer {self._require_api_key()}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        self._raise_for_minimax(response, "voice clone")
        result = response.json()
        result["voice_id"] = voice_id
        result["clone_file_id"] = clone_file_id
        return result

    @staticmethod
    def _raise_for_minimax(
        response: httpx.Response, operation: str
    ) -> None:
        if response.status_code >= 400:
            raise VoiceRenderError(
                f"MiniMax {operation} returned HTTP "
                f"{response.status_code}: {response.text[:300]}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise VoiceRenderError(
                f"MiniMax {operation} returned invalid JSON"
            ) from exc
        base = body.get("base_resp") or {}
        if base.get("status_code") not in (None, 0):
            raise VoiceRenderError(
                f"MiniMax {operation} error {base.get('status_code')}: "
                f"{base.get('status_msg', 'unknown error')}"
            )


def prepare_clone_samples(
    input_video: Path,
    output_dir: Path,
    *,
    clone_start: float = 11.35,
    clone_end: float = 60.35,
    prompt_start: float = 46.15,
    prompt_end: float = 52.05,
) -> tuple[Path, Path]:
    """Extract the single-speaker benchmark intervals as lossless PCM WAV."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VoiceRenderError(
            "ffmpeg is required to prepare clone samples"
        )
    video = input_video.resolve()
    if not video.is_file():
        raise VoiceRenderError(f"Input video not found: {video}")
    if not (
        0 <= clone_start < clone_end
        and 0 <= prompt_start < prompt_end
    ):
        raise VoiceRenderError("Invalid clone/prompt time range")
    if prompt_end - prompt_start >= 8:
        raise VoiceRenderError(
            "MiniMax prompt_audio must be shorter than 8 seconds"
        )
    if not (10 <= clone_end - clone_start <= 300):
        raise VoiceRenderError(
            "MiniMax clone audio must be 10 seconds to 5 minutes"
        )

    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    clone_output = destination / "luyao-clone-48s.wav"
    prompt_output = destination / "luyao-prompt-5s.wav"
    for start, end, output in (
        (clone_start, clone_end, clone_output),
        (prompt_start, prompt_end, prompt_output),
    ):
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{start:.2f}",
                "-to",
                f"{end:.2f}",
                "-i",
                str(video),
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-ar",
                "44100",
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            check=True,
        )
    return clone_output, prompt_output


async def _clone_from_cli(args: argparse.Namespace) -> None:
    settings = AppSettings.from_env()
    agent = VoiceRenderAgent(settings)
    try:
        result = await agent.clone_voice(
            Path(args.audio),
            args.voice_id,
            prompt_audio=(
                Path(args.prompt_audio) if args.prompt_audio else None
            ),
            prompt_text=args.prompt_text,
            preview_text=args.preview,
            noise_reduction=not args.no_noise_reduction,
            volume_normalization=not args.no_volume_normalization,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await agent.close()


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Luyao MiniMax voice utilities"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare", help="Extract clone samples from 123.mp4"
    )
    prepare.add_argument("--input", default="123.mp4")
    prepare.add_argument(
        "--output-dir", default="minimax-output/voice-clone"
    )
    prepare.add_argument("--clone-start", type=float, default=11.35)
    prepare.add_argument("--clone-end", type=float, default=60.35)
    prepare.add_argument("--prompt-start", type=float, default=46.15)
    prepare.add_argument("--prompt-end", type=float, default=52.05)

    clone = commands.add_parser(
        "clone", help="Upload samples and create a voice_id"
    )
    clone.add_argument("--audio", required=True)
    clone.add_argument("--voice-id", default="luyao_voice_v1")
    clone.add_argument("--prompt-audio")
    clone.add_argument("--prompt-text")
    clone.add_argument(
        "--preview", default="阿雾，我会用自己的名字，一直陪你走下去。"
    )
    clone.add_argument("--no-noise-reduction", action="store_true")
    clone.add_argument(
        "--no-volume-normalization", action="store_true"
    )
    return parser


def main() -> None:
    args = _build_cli().parse_args()
    if args.command == "prepare":
        outputs = prepare_clone_samples(
            Path(args.input),
            Path(args.output_dir),
            clone_start=args.clone_start,
            clone_end=args.clone_end,
            prompt_start=args.prompt_start,
            prompt_end=args.prompt_end,
        )
        print("\n".join(str(path) for path in outputs))
    else:
        asyncio.run(_clone_from_cli(args))


if __name__ == "__main__":
    main()

