import unittest
from types import SimpleNamespace

from config import AppSettings
from guardrails import SAFE_PERSONA_REPLY, PersonaGuardrail
from memory import LLMMemoryExtractor
from persona import PersonaAgent


class RecordingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            async def chunks():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                reasoning_details=[{"text": "internal"}],
                            )
                        )
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="[whisper] 阿雾，我在。")
                        )
                    ]
                )

            return chunks()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))]
        )


class RecordingClient:
    def __init__(self) -> None:
        self.completions = RecordingCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class MiniMaxReasoningTests(unittest.IsolatedAsyncioTestCase):
    async def test_persona_ignores_blank_stream_phrases(self) -> None:
        for deltas in (
            ["\n", "[whisper] 阿雾，早上好。"],
            ["  \n\n[whisper] 阿雾，早上好。", "\n\n", "今天慢慢来。"],
        ):
            with self.subTest(deltas=deltas):
                async def create(**kwargs):
                    async def chunks():
                        for delta in deltas:
                            yield SimpleNamespace(choices=[SimpleNamespace(
                                delta=SimpleNamespace(content=delta)
                            )])
                    return chunks()

                client = SimpleNamespace(chat=SimpleNamespace(
                    completions=SimpleNamespace(create=create)
                ))
                agent = PersonaAgent(client, AppSettings(), PersonaGuardrail())
                reply = await agent.reply(
                    user_message="早上好。", history=[], memories=[]
                )
                self.assertIn("早上好。", reply)
                self.assertNotIn(SAFE_PERSONA_REPLY, reply)
                if len(deltas) == 3:
                    self.assertIn("今天慢慢来。", reply)

    async def test_persona_keeps_fallback_for_entirely_blank_stream(self) -> None:
        async def create(**kwargs):
            async def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content=" \n\n")
                )])
            return chunks()

        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)
        ))
        agent = PersonaAgent(client, AppSettings(), PersonaGuardrail())
        reply = await agent.reply(
            user_message="早上好。", history=[], memories=[]
        )
        self.assertEqual(reply, SAFE_PERSONA_REPLY)

    async def test_persona_splits_reasoning_from_visible_stream(self) -> None:
        client = RecordingClient()
        agent = PersonaAgent(client, AppSettings(), PersonaGuardrail())

        reply = await agent.reply(
            user_message="你在吗？",
            history=[],
            memories=[],
        )

        self.assertEqual(reply, "[whisper] 阿雾，我在。")
        self.assertEqual(
            client.completions.calls[0]["extra_body"],
            {"reasoning_split": True},
        )

    async def test_memory_extractor_splits_reasoning_from_json(self) -> None:
        client = RecordingClient()
        extractor = LLMMemoryExtractor(client, "MiniMax-M2.7")

        records = await extractor.extract(
            user_id="awu_001",
            user_message="我喜欢白色拍立得",
            assistant_message="我记住了。",
        )

        self.assertEqual(records, [])
        self.assertEqual(
            client.completions.calls[0]["extra_body"],
            {"reasoning_split": True},
        )


if __name__ == "__main__":
    unittest.main()
