"""Application orchestration across Persona, Memory, Guardrail, and Voice agents."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from config import AppSettings
from guardrails import PersonaGuardrail
from memory import ExtractionJob, MemoryWorkerAgent, RetrievedMemory
from persona import PersonaAgent
from schemas import ChatRequest, ChatResponse, RetrievedMemoryModel
from voice import VoiceRenderAgent


logger = logging.getLogger(__name__)


class ServiceConfigurationError(RuntimeError):
    pass


class LuyaoService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        guardrail: PersonaGuardrail,
        memory: MemoryWorkerAgent,
        persona: PersonaAgent | None,
        voice: VoiceRenderAgent,
    ) -> None:
        self.settings = settings
        self.guardrail = guardrail
        self.memory = memory
        self.persona = persona
        self.voice = voice

    @staticmethod
    def trace_id(requested: str | None) -> str:
        return requested or f"req_{uuid.uuid4().hex}"

    @staticmethod
    def _memory_models(
        memories: list[RetrievedMemory],
    ) -> list[RetrievedMemoryModel]:
        return [
            RetrievedMemoryModel(
                id=memory.id,
                entity=memory.entity,
                category=memory.category,
                context_summary=memory.context_summary,
                emotional_weight=memory.emotional_weight,
                score=memory.score,
            )
            for memory in memories
        ]

    def _require_persona(self) -> PersonaAgent:
        if self.persona is None:
            raise ServiceConfigurationError(
                "MINIMAX_API_KEY is not configured on the backend"
            )
        return self.persona

    async def chat(self, request: ChatRequest) -> ChatResponse:
        trace_id = self.trace_id(request.trace_id)
        decision = self.guardrail.inspect_input(request.user_message)
        if decision.blocked:
            raw_text = decision.safe_reply or ""
            awakening = False
            memories: list[RetrievedMemory] = []
        else:
            persona = self._require_persona()
            memories = await self.memory.retrieve(
                request.user_id, request.user_message
            )
            raw_text = await persona.reply(
                user_message=request.user_message,
                history=request.chat_history,
                memories=memories,
                vision_context=request.vision_context,
                injection_detected=decision.injection_detected,
            )
            awakening = persona.has_awakening_trigger(request.user_message)
            self._enqueue_extraction(request, raw_text, trace_id)

        emotion = (
            PersonaAgent.emotion_state(raw_text, awakening)
            if raw_text
            else "gentle"
        )
        logger.info(
            "chat complete",
            extra={
                "trace_id": trace_id,
                "memory_count": len(memories),
                "awakening": awakening,
                "injection_detected": decision.injection_detected,
            },
        )
        return ChatResponse(
            trace_id=trace_id,
            raw_text=raw_text,
            emotion_state=emotion,
            has_awakening_trigger=awakening,
            injection_detected=decision.injection_detected,
            retrieved_memories=self._memory_models(memories),
        )

    async def stream_chat(
        self, request: ChatRequest
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        trace_id = self.trace_id(request.trace_id)
        decision = self.guardrail.inspect_input(request.user_message)

        if decision.blocked:
            yield "meta", {
                "trace_id": trace_id,
                "retrieved_memories": [],
                "injection_detected": decision.injection_detected,
            }
            raw_text = decision.safe_reply or ""
            yield "text_delta", {"text": raw_text}
            yield "done", {
                "trace_id": trace_id,
                "raw_text": raw_text,
                "emotion_state": "gentle",
                "has_awakening_trigger": False,
                "injection_detected": decision.injection_detected,
            }
            return

        persona = self._require_persona()
        memories = await self.memory.retrieve(
            request.user_id, request.user_message
        )
        yield "meta", {
            "trace_id": trace_id,
            "retrieved_memories": [
                item.model_dump()
                for item in self._memory_models(memories)
            ],
            "injection_detected": decision.injection_detected,
        }

        parts: list[str] = []
        async for text in persona.stream_reply(
            user_message=request.user_message,
            history=request.chat_history,
            memories=memories,
            vision_context=request.vision_context,
            injection_detected=decision.injection_detected,
        ):
            parts.append(text)
            yield "text_delta", {"text": text}

        raw_text = self.guardrail.inspect_output("".join(parts)).text
        awakening = persona.has_awakening_trigger(request.user_message)
        emotion = PersonaAgent.emotion_state(raw_text, awakening)
        self._enqueue_extraction(request, raw_text, trace_id)
        yield "done", {
            "trace_id": trace_id,
            "raw_text": raw_text,
            "emotion_state": emotion,
            "has_awakening_trigger": awakening,
            "injection_detected": decision.injection_detected,
        }

    def _enqueue_extraction(
        self,
        request: ChatRequest,
        assistant_message: str,
        trace_id: str,
    ) -> None:
        self.memory.enqueue(
            ExtractionJob(
                user_id=request.user_id,
                user_message=request.user_message,
                assistant_message=assistant_message,
                trace_id=trace_id,
            )
        )

