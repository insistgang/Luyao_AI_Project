import io
import unittest
import wave

from config import AppSettings
from voice import (
    EmotionTagParser,
    VoiceRenderAgent,
    VoiceRenderError,
    VoiceStyle,
)


class FakeVoiceRenderAgent(VoiceRenderAgent):
    def __init__(self, settings):
        super().__init__(settings)
        self.requested_segments = []

    async def _stream_segment(self, segment, voice_id):
        self.requested_segments.append(segment)
        yield b"\x01\x02"


class EmotionTagParserTests(unittest.TestCase):
    def test_parses_styles_and_pause(self) -> None:
        segments = EmotionTagParser().parse(
            "第一句[pause][whisper] 第二句 [sigh] 第三句"
        )
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0].style, VoiceStyle.DEFAULT)
        self.assertEqual(segments[0].pause_after_ms, 400)
        self.assertEqual(segments[1].style, VoiceStyle.WHISPER)
        self.assertEqual(segments[2].style, VoiceStyle.SIGH)
        self.assertTrue(segments[2].sigh_prefix)


class VoiceRenderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = AppSettings(
            minimax_api_key="test-key",
            minimax_voice_id="luyao_voice_v1",
            audio_sample_rate=32000,
        )
        self.agent = FakeVoiceRenderAgent(self.settings)

    async def asyncTearDown(self) -> None:
        await self.agent.close()

    async def test_tagged_reply_uses_exactly_one_tts_request(self) -> None:
        chunks = [
            chunk
            async for chunk in self.agent.stream_pcm(
                "[sigh] 前一句[pause][whisper]后一句",
                voice_id="luyao_voice_v1",
            )
        ]
        self.assertEqual(chunks, [b"\x01\x02"])
        self.assertEqual(len(self.agent.requested_segments), 1)
        segment = self.agent.requested_segments[0]
        self.assertEqual(segment.style, VoiceStyle.SIGH)
        self.assertIn("(sighs)", segment.text)
        self.assertIn("<#0.40#>", segment.text)
        self.assertNotIn("[whisper]", segment.text)

    async def test_render_wav_has_expected_format(self) -> None:
        payload = await self.agent.render_wav("阿雾")
        self.assertEqual(len(self.agent.requested_segments), 1)
        with wave.open(io.BytesIO(payload), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), 32000)

    async def test_clone_rejects_invalid_voice_id_before_network(self) -> None:
        with self.assertRaises(VoiceRenderError):
            await self.agent.clone_voice(
                clone_audio=None,
                voice_id="_invalid",
            )

    def test_style_uses_compatible_models(self) -> None:
        segments = EmotionTagParser().parse(
            "[whisper]轻声[sigh]叹气"
        )
        whisper_model, whisper_setting, _ = self.agent._voice_setting(
            segments[0], "luyao_voice_v1"
        )
        sigh_model, sigh_setting, sigh_text = self.agent._voice_setting(
            segments[1], "luyao_voice_v1"
        )
        self.assertEqual(whisper_model, "speech-2.6-hd")
        self.assertEqual(whisper_setting["emotion"], "whisper")
        self.assertEqual(sigh_model, "speech-2.8-hd")
        self.assertEqual(sigh_setting["emotion"], "sad")
        self.assertTrue(sigh_text.startswith("(sighs)"))


if __name__ == "__main__":
    unittest.main()

