import unittest
from unittest.mock import AsyncMock, patch

import httpx

import ui
from tests.test_ui_flow import FakeAsyncClient


class HealthResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return SubmissionClient.health


class SubmissionClient(FakeAsyncClient):
    health = {}
    error = None

    async def get(self, url):
        if type(self).error:
            raise type(self).error
        return HealthResponse()


class SubmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        SubmissionClient.health = {"status": "ok", "config": {"llm_configured": True, "minimax_configured": True}}
        SubmissionClient.error = None
        SubmissionClient.voice_calls = 0
        SubmissionClient.stream_payloads = []
        ui._PROCESSING_LOCK.clear()
        ui._RECENT_COMPLETIONS.clear()

    async def collect(self, text="待发送内容", history=None, voice=True, state=None):
        with (
            patch.object(ui.httpx, "AsyncClient", SubmissionClient),
            patch.object(ui, "BUBBLE_DELAY_SECONDS", 0),
            patch.object(ui.asyncio, "sleep", AsyncMock()),
        ):
            return [value async for value in ui.submit_message(text, history or [], voice, state)]

    async def test_missing_configuration_preserves_draft_and_history(self):
        history = [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回复"}]
        SubmissionClient.health = {"status": "degraded", "config": {"llm_configured": False, "minimax_configured": False}}
        outputs = await self.collect(history=history)
        self.assertEqual(outputs[-1][0]["value"], "待发送内容")
        self.assertEqual(outputs[-1][1], history)
        self.assertIn("未配置", outputs[-1][3])
        self.assertEqual(SubmissionClient.stream_payloads, [])
        self.assertEqual(SubmissionClient.voice_calls, 0)
        self.assertTrue(outputs[-1][5]["visible"])
        self.assertFalse(outputs[-1][6]["visible"])

    async def test_unreachable_backend_keeps_the_draft_without_a_fake_reply(self):
        SubmissionClient.error = httpx.ConnectError("sensitive-transport-detail")
        outputs = await self.collect()
        self.assertEqual(outputs[-1][0]["value"], "待发送内容")
        self.assertEqual(outputs[-1][1], [])
        self.assertNotIn("sensitive-transport-detail", outputs[-1][3])
        self.assertEqual(SubmissionClient.stream_payloads, [])

    async def test_ready_submission_swaps_busy_controls_and_restores_them(self):
        outputs = await self.collect()
        self.assertFalse(outputs[0][0]["interactive"])
        self.assertFalse(outputs[0][5]["visible"])
        self.assertTrue(outputs[0][6]["visible"])
        self.assertTrue(outputs[-1][0]["interactive"])
        self.assertTrue(outputs[-1][5]["visible"])
        self.assertFalse(outputs[-1][6]["visible"])
        self.assertEqual(len(SubmissionClient.stream_payloads), 1)

    async def test_text_chat_does_not_call_unavailable_voice(self):
        SubmissionClient.health = {"status": "degraded", "config": {"llm_configured": True, "minimax_configured": False}}
        outputs = await self.collect()
        self.assertEqual(len(SubmissionClient.stream_payloads), 1)
        self.assertEqual(SubmissionClient.voice_calls, 0)
        self.assertFalse(outputs[-1][7]["value"])

    def test_stop_preserves_a_partial_reply_in_model_history(self):
        history = [{"role": "user", "content": "正在问"}, {"role": "assistant", "content": "部分回复"}]
        state = {**ui._new_conversation_state([], history), "voice_ready": True, "pending_turn": True}
        outputs = ui.stop_submission("", history, state)
        self.assertEqual(outputs[4]["model_history"], history)
        self.assertTrue(outputs[0]["interactive"])
        self.assertFalse(outputs[6]["visible"])
        self.assertIsNone(outputs[2])

    def test_stop_restores_a_draft_when_no_reply_was_received(self):
        history = [{"role": "user", "content": "还没收到回复"}]
        state = {**ui._new_conversation_state([], history), "pending_turn": True}
        outputs = ui.stop_submission("", history, state)
        self.assertEqual(outputs[0]["value"], "还没收到回复")
        self.assertEqual(outputs[1], [])

    async def test_cancel_closes_the_nested_stream_and_releases_its_lock(self):
        with patch.object(ui.httpx, "AsyncClient", SubmissionClient):
            generator = ui.submit_message("取消测试", [], False, None)
            await anext(generator)
            await anext(generator)
            self.assertEqual(len(ui._PROCESSING_LOCK), 1)
            await generator.aclose()
        self.assertEqual(ui._PROCESSING_LOCK, set())

    def test_stop_keeps_completed_text_while_voice_is_being_prepared(self):
        display = [{"role": "user", "content": "准备语音"}]
        model = [*display, {"role": "assistant", "content": "第一句。[pause] 第二句。"}]
        state = {**ui._new_conversation_state(model, display), "pending_turn": True, "model_complete": True}
        outputs = ui.stop_submission("", display, state)
        self.assertEqual([item["content"] for item in outputs[1]], ["准备语音", "第一句。", "第二句。"])
        self.assertEqual(outputs[0]["value"], "")

    def test_duplicate_protection_is_scoped_to_each_browser_session(self):
        self.assertNotEqual(ui._submission_key("你好", [], "session-a"), ui._submission_key("你好", [], "session-b"))

    def test_stop_preserves_raw_prior_model_history(self):
        model = [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "[whisper] 旧回复。[pause] 继续。"}]
        display = [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回复。\n继续。"}, {"role": "user", "content": "新问题"}, {"role": "assistant", "content": "部分新回复"}]
        state = {**ui._new_conversation_state(model, display), "pending_turn": True}
        output = ui.stop_submission("", display, state)
        self.assertEqual(output[4]["model_history"][:2], model)
        self.assertEqual(output[4]["model_history"][-2:], display[-2:])

    def test_stop_preserves_the_completed_raw_reply_during_voice(self):
        display = [{"role": "user", "content": "准备语音"}]
        model = [*display, {"role": "assistant", "content": "[whisper] 第一句。[pause] 第二句。"}]
        state = {**ui._new_conversation_state(model, display), "pending_turn": True, "model_complete": True}
        output = ui.stop_submission("", display, state)
        self.assertEqual(output[4]["model_history"], model)

    def test_health_refresh_only_updates_the_connection_badge(self):
        functions = [fn for fn in ui.demo.fns.values() if getattr(fn.fn, "__name__", "") in {"backend_health", "refresh_ui"}]
        self.assertGreaterEqual(len(functions), 2)
        for fn in functions:
            self.assertEqual([component.elem_id for component in fn.outputs], ["luyao-connection"])

    async def test_degraded_optional_services_do_not_block_configured_chat(self):
        SubmissionClient.health = {"status": "degraded", "config": {"llm_configured": True, "minimax_configured": True}}
        await self.collect(voice=False)
        self.assertEqual(len(SubmissionClient.stream_payloads), 1)
