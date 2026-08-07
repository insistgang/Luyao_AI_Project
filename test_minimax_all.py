"""Manual all-MiniMax online smoke test."""

import asyncio

from config import AppSettings
from main import _build_service
from schemas import ChatRequest
from voice import VoiceRenderAgent


async def main() -> None:
    settings = AppSettings.from_env()
    if not settings.minimax_api_key:
        raise RuntimeError("请先设置 MINIMAX_API_KEY")

    print("=== MiniMax Full Integration Test ===")
    print("Chat:", settings.llm_base_url, settings.llm_model)
    print("Speech:", settings.minimax_api_host, settings.minimax_model)
    print("Voice ID:", settings.minimax_voice_id)

    service, llm_client = _build_service(settings)
    await service.memory.start()
    try:
        req1 = ChatRequest(
            user_id="awu_001",
            user_message="我前女友后天要结婚了，我能送她什么？",
            chat_history=[],
        )
        resp1 = await service.chat(req1)
        print("\n[Luyao Reply]:\n", resp1.raw_text)

        req2 = ChatRequest(
            user_id="awu_001",
            user_message="你怎么知道？",
            chat_history=[
                {
                    "role": "user",
                    "content": "我前女友后天要结婚了，我能送她什么？",
                },
                {"role": "assistant", "content": resp1.raw_text},
            ],
        )
        resp2 = await service.chat(req2)
        print("\n[Luyao Awakening Reply]:\n", resp2.raw_text)

        voice_agent = VoiceRenderAgent(settings)
        try:
            audio_bytes = await voice_agent.render_wav(resp1.raw_text)
            print("TTS WAV bytes:", len(audio_bytes))
        finally:
            await voice_agent.close()
    finally:
        await service.memory.stop()
        await service.voice.close()
        if llm_client is not None:
            await llm_client.close()


if __name__ == "__main__":
    asyncio.run(main())

