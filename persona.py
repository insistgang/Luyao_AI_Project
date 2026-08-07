"""Persona Agent with sentence-safe streaming."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from config import AppSettings, generate_system_prompt
from guardrails import PersonaGuardrail
from memory import RetrievedMemory
from schemas import ChatMessage


AWAKENING_PATTERN = re.compile(
    r"(?:你怎么知道|你怎么会知道|为什么知道|你是谁|替代品|你会离开|你想离开)",
    re.IGNORECASE,
)
_PHRASE_BOUNDARY = re.compile(r"[\s\S]+?(?:[。！？!?]+|…{2,}|\n+)")


def split_complete_phrases(buffer: str) -> tuple[list[str], str]:
    phrases: list[str] = []
    consumed = 0
    for match in _PHRASE_BOUNDARY.finditer(buffer):
        phrases.append(match.group(0))
        consumed = match.end()
    return phrases, buffer[consumed:]


class PersonaAgent:
    def __init__(
        self,
        client: Any,
        settings: AppSettings,
        guardrail: PersonaGuardrail,
    ) -> None:
        self._client = client
        self._settings = settings
        self._guardrail = guardrail

    @staticmethod
    def has_awakening_trigger(message: str) -> bool:
        return bool(AWAKENING_PATTERN.search(message))

    @staticmethod
    def emotion_state(text: str, awakening: bool) -> str:
        if awakening:
            return "resonation"
        if "[sigh]" in text:
            return "melancholy"
        if "[whisper]" in text:
            return "tender"
        return "gentle"

    def _messages(
        self,
        *,
        user_message: str,
        history: Sequence[ChatMessage],
        memories: Sequence[RetrievedMemory],
        vision_context: str,
        injection_detected: bool,
    ) -> list[dict[str, str]]:
        system_prompt = generate_system_prompt(
            [memory.prompt_text for memory in memories],
            vision_context,
            injection_detected=injection_detected,
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(
            {"role": message.role, "content": message.content} for message in history
        )
        messages.append({"role": "user", "content": user_message})
        return messages

    async def stream_reply(
        self,
        *,
        user_message: str,
        history: Sequence[ChatMessage],
        memories: Sequence[RetrievedMemory],
        vision_context: str = "",
        injection_detected: bool = False,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._settings.llm_model,
            messages=self._messages(
                user_message=user_message,
                history=history,
                memories=memories,
                vision_context=vision_context,
                injection_detected=injection_detected,
            ),
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
            extra_body={"reasoning_split": True},
            stream=True,
        )
        buffer = ""
        emitted = False
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if not delta:
                continue
            buffer += delta
            phrases, buffer = split_complete_phrases(buffer)
            for phrase in phrases:
                checked = self._guardrail.inspect_output(phrase)
                yield checked.text
                emitted = True
                if checked.replaced:
                    return

        if buffer.strip():
            checked = self._guardrail.inspect_output(buffer)
            yield checked.text
            emitted = True
        if not emitted:
            yield self._guardrail.inspect_output("").text

    async def reply(
        self,
        *,
        user_message: str,
        history: Sequence[ChatMessage],
        memories: Sequence[RetrievedMemory],
        vision_context: str = "",
        injection_detected: bool = False,
    ) -> str:
        parts = [
            part
            async for part in self.stream_reply(
                user_message=user_message,
                history=history,
                memories=memories,
                vision_context=vision_context,
                injection_detected=injection_detected,
            )
        ]
        checked = self._guardrail.inspect_output("".join(parts))
        return checked.text

