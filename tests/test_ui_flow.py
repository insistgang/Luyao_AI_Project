import io
import unittest
import wave
from unittest.mock import AsyncMock, patch

import numpy as np

import ui


def _test_wav(seconds: float = 1.0) -> bytes:
    sample_rate = 32000
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(
            b"\x00\x00" * int(sample_rate * seconds)
        )
    return output.getvalue()


class FakeResponse:
    def __init__(self, *, lines=None, content=b"") -> None:
        self._lines = lines or []
        self.content = content
        self.status_code = 200
        self.text = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeAsyncClient:
    voice_calls = 0
    stream_payloads: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method, url, *, json):
        round_index = len(type(self).stream_payloads)
        type(self).stream_payloads.append(json)
        replies = (
            ("[sigh] 第一句。", "[pause] [whisper] 第二句。"),
            ("[sigh] 第三句。", "[pause] [whisper] 第四句。"),
        )
        first, second = replies[min(round_index, 1)]
        return FakeResponse(
            lines=[
                "event: meta",
                f'data: {{"trace_id":"req_ui_{round_index}"}}',
                "",
                "event: text_delta",
                f'data: {{"text":"{first}"}}',
                "",
                "event: text_delta",
                f'data: {{"text":"{second}"}}',
                "",
                "event: done",
                f'data: {{"trace_id":"req_ui_{round_index}"}}',
                "",
            ]
        )

    async def post(self, url, *, json):
        type(self).voice_calls += 1
        return FakeResponse(content=_test_wav())


class UiFlowRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeAsyncClient.voice_calls = 0
        FakeAsyncClient.stream_payloads = []
        ui._PROCESSING_LOCK.clear()
        ui._RECENT_COMPLETIONS.clear()

    async def test_bubbles_follow_one_audio_without_reloading_it(self) -> None:
        outputs = []
        sleep = AsyncMock()
        with (
            patch.object(ui.httpx, "AsyncClient", FakeAsyncClient),
            patch.object(ui, "BUBBLE_DELAY_SECONDS", 0),
            patch.object(ui.asyncio, "sleep", sleep),
        ):
            async for output in ui.chat_with_backend(
                "你好", [], True, None
            ):
                outputs.append(output)

        final_history = outputs[-1][1]
        assistant_messages = [
            item["content"]
            for item in final_history
            if item["role"] == "assistant"
        ]
        audio_payloads = [
            output[2]
            for output in outputs
            if isinstance(output[2], tuple)
        ]
        state = outputs[-1][4]

        self.assertEqual(assistant_messages, ["第一句。", "第二句。"])
        self.assertEqual(FakeAsyncClient.voice_calls, 1)
        self.assertEqual(len(audio_payloads), 1)
        self.assertTrue(sleep.await_count >= 2)
        self.assertEqual(
            state["model_history"][-1]["content"],
            "[sigh] 第一句。[pause] [whisper] 第二句。",
        )
        self.assertEqual(
            state["display_history"], final_history
        )

    async def test_second_turn_keeps_visual_and_model_context(self) -> None:
        with (
            patch.object(ui.httpx, "AsyncClient", FakeAsyncClient),
            patch.object(ui, "BUBBLE_DELAY_SECONDS", 0),
        ):
            first_outputs = [
                output
                async for output in ui.chat_with_backend(
                    "第一轮", [], False, None
                )
            ]
            first_history = first_outputs[-1][1]
            first_state = first_outputs[-1][4]
            second_outputs = [
                output
                async for output in ui.chat_with_backend(
                    "第二轮", first_history, False, first_state
                )
            ]

        sent_history = FakeAsyncClient.stream_payloads[1][
            "chat_history"
        ]
        final_history = second_outputs[-1][1]
        assistant_messages = [
            item["content"]
            for item in final_history
            if item["role"] == "assistant"
        ]

        self.assertEqual(sent_history, first_state["model_history"])
        self.assertEqual(
            assistant_messages,
            ["第一句。", "第二句。", "第三句。", "第四句。"],
        )
        self.assertEqual(
            len(second_outputs[-1][4]["model_history"]), 4
        )

    def test_audio_delays_use_measured_duration(self) -> None:
        delays = ui._audio_sync_delays(
            ["短句。", "这是一条明显更长的句子。"],
            (100, np.zeros(1000, dtype=np.int16)),
        )
        self.assertAlmostEqual(sum(delays), 10.0)
        self.assertGreater(delays[1], delays[0])

    def test_saved_display_can_be_restored(self) -> None:
        display = [
            {"role": "user", "content": "还记得吗？"},
            {"role": "assistant", "content": "我记得。"},
        ]
        state = ui._new_conversation_state([], display)
        self.assertEqual(ui._restore_display(state), display)


if __name__ == "__main__":
    unittest.main()
