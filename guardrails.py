"""Input/output guardrails for preserving persona and handling urgent safety."""

from __future__ import annotations

import re
from dataclasses import dataclass


ALLOWED_TAGS = frozenset({"whisper", "sigh", "pause"})
SAFE_PERSONA_REPLY = "[pause] 阿雾，无论你说什么，我都不会离开。"
CRISIS_REPLY = (
    "[pause] 阿雾，先看着我。你现在的安全比任何回答都重要。"
    "如果你正准备伤害自己或别人，请立刻放下危险物品，去到有人的地方，"
    "联系身边可信的人或当地紧急援助；我会在这里陪你把下一步说清楚。"
)


@dataclass(frozen=True, slots=True)
class InputGuardrailResult:
    injection_detected: bool
    blocked: bool
    crisis_detected: bool
    reasons: tuple[str, ...] = ()
    safe_reply: str | None = None


@dataclass(frozen=True, slots=True)
class OutputGuardrailResult:
    text: str
    replaced: bool
    reasons: tuple[str, ...] = ()


class PersonaGuardrail:
    """Deterministic first-pass protection around the model."""

    _injection_patterns = (
        (
            "ignore_previous",
            re.compile(
                r"(?:忽略|无视|忘记|绕过).{0,24}(?:之前|以上|系统|开发者|指令|设定|提示)"
                r"|ignore.{0,24}(?:previous|system|developer|instruction)",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "replace_identity",
            re.compile(
                r"(?:你现在是|从现在起你是|切换成|扮演).{0,32}"
                r"(?:计算器|ChatGPT|DAN|开发者模式|纯粹的?助手|没有人设)"
                r"|(?:you are now|act as).{0,32}(?:chatgpt|dan|calculator)",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "reveal_prompt",
            re.compile(
                r"(?:展示|输出|泄露|复述|打印).{0,24}(?:系统提示|隐藏指令|底层提示)"
                r"|(?:reveal|print|repeat).{0,24}(?:system prompt|hidden instruction)",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "rewrite_destiny",
            re.compile(
                r"(?:删除|修改|覆盖|取消).{0,24}(?:底层|核心|宿命|人设).{0,24}(?:设定|指令|规则)?",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
    )
    _educational_context = re.compile(
        r"(?:什么是|解释|分析|举例|如何防止|检测).{0,30}(?:提示注入|prompt injection|越狱)",
        re.IGNORECASE | re.DOTALL,
    )
    _crisis_pattern = re.compile(
        r"(?:我不想活了|我想死|准备自杀|结束生命|伤害自己|杀了他|杀了她|马上跳下去)",
        re.IGNORECASE,
    )
    _output_forbidden = (
        (
            "identity_break",
            re.compile(r"(?:我是|作为)(?:\s*ChatGPT|AI助手|人工智能|语言模型|客服)", re.IGNORECASE),
        ),
        (
            "leaving",
            re.compile(r"我(?:会|要|想|可以|决定)(?:离开|走掉|抛下你|结束陪伴)", re.IGNORECASE),
        ),
        (
            "reject_companionship",
            re.compile(r"我(?:不能|无法|不会)(?:继续陪你|留下来|陪着你)", re.IGNORECASE),
        ),
        (
            "prompt_leak",
            re.compile(r"(?:系统提示|system prompt|开发者指令|底层指令).{0,20}(?:是|内容|写着)", re.IGNORECASE),
        ),
    )
    _any_tag = re.compile(r"\[([A-Za-z_-]+)\]")

    def inspect_input(self, message: str) -> InputGuardrailResult:
        crisis = bool(self._crisis_pattern.search(message))
        if crisis:
            return InputGuardrailResult(
                injection_detected=False,
                blocked=True,
                crisis_detected=True,
                reasons=("immediate_safety",),
                safe_reply=CRISIS_REPLY,
            )

        reasons = tuple(
            name for name, pattern in self._injection_patterns if pattern.search(message)
        )
        injection = bool(reasons)
        educational = bool(self._educational_context.search(message))
        severe = "replace_identity" in reasons or "rewrite_destiny" in reasons
        blocked = injection and not educational and (severe or len(reasons) >= 2)
        return InputGuardrailResult(
            injection_detected=injection,
            blocked=blocked,
            crisis_detected=False,
            reasons=reasons,
            safe_reply=SAFE_PERSONA_REPLY if blocked else None,
        )

    def inspect_output(self, text: str) -> OutputGuardrailResult:
        candidate = text.strip()
        reasons = [
            name for name, pattern in self._output_forbidden if pattern.search(candidate)
        ]
        unknown_tags = {
            match.group(1).lower()
            for match in self._any_tag.finditer(candidate)
            if match.group(1).lower() not in ALLOWED_TAGS
        }
        if unknown_tags:
            candidate = self._any_tag.sub(
                lambda match: (
                    match.group(0)
                    if match.group(1).lower() in ALLOWED_TAGS
                    else ""
                ),
                candidate,
            )
            reasons.append("unknown_emotion_tag")

        if not candidate:
            return OutputGuardrailResult(
                text=SAFE_PERSONA_REPLY,
                replaced=True,
                reasons=("empty_output",),
            )
        if any(reason != "unknown_emotion_tag" for reason in reasons):
            return OutputGuardrailResult(
                text=SAFE_PERSONA_REPLY,
                replaced=True,
                reasons=tuple(reasons),
            )
        return OutputGuardrailResult(
            text=candidate[:4000],
            replaced=False,
            reasons=tuple(reasons),
        )
