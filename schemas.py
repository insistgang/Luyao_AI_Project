"""Validated API and inter-agent schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    trace_id: str | None = Field(default=None, min_length=8, max_length=128)
    user_id: str = Field(default="awu_001", min_length=1, max_length=128)
    user_message: str = Field(
        min_length=1,
        max_length=8000,
        validation_alias=AliasChoices("user_message", "message"),
    )
    vision_context: str = Field(default="", max_length=3000)
    chat_history: list[ChatMessage] = Field(default_factory=list, max_length=40)


class RetrievedMemoryModel(BaseModel):
    id: str
    entity: str
    category: str
    context_summary: str
    emotional_weight: int = Field(ge=1, le=10)
    score: float = Field(ge=0.0, le=1.0)


class ChatResponse(BaseModel):
    trace_id: str
    raw_text: str
    emotion_state: str
    has_awakening_trigger: bool
    injection_detected: bool = False
    retrieved_memories: list[RetrievedMemoryModel] = Field(default_factory=list)


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10000)
    voice_id: str | None = Field(default=None, min_length=8, max_length=256)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    config: dict[str, object]
    memory_worker_running: bool
