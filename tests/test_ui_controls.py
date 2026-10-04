import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ui


class FakeHealthResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeHealthClient:
    payload: dict = {}
    error: Exception | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url: str) -> FakeHealthResponse:
        if type(self).error is not None:
            raise type(self).error
        return FakeHealthResponse(type(self).payload)


class UiControlRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeHealthClient.payload = {}
        FakeHealthClient.error = None

    def _component_ids(self) -> set[str | None]:
        config = ui.demo.get_config_file()
        return {
            component.get("props", {}).get("elem_id")
            for component in config["components"]
        }

    def test_launch_options_use_existing_avatar_as_favicon(self) -> None:
        options = ui.launch_options()
        expected_path = (
            Path(ui.__file__).resolve().parent
            / "assets"
            / "ui"
            / "luyao-avatar.png"
        )

        self.assertEqual(Path(options["favicon_path"]).resolve(), expected_path)
        self.assertTrue(expected_path.is_file())

    def test_browser_state_secret_persists_with_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "browser-state.key"
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LUYAO_BROWSER_STATE_SECRET", None)
                first = ui._browser_state_secret(target)
                second = ui._browser_state_secret(target)

            self.assertTrue(first)
            self.assertEqual(second, first)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_browser_state_secret_environment_override_skips_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "browser-state.key"
            override = "test-browser-state-secret"
            with patch.dict(
                os.environ,
                {"LUYAO_BROWSER_STATE_SECRET": override},
                clear=False,
            ):
                result = ui._browser_state_secret(target)

            self.assertEqual(result, override)
            self.assertFalse(target.exists())

    def test_chat_controls_have_stable_element_ids(self) -> None:
        component_ids = self._component_ids()

        self.assertTrue(
            {"luyao-chat", "luyao-message", "luyao-send"}
            <= component_ids
        )

    def test_reset_clears_conversation_without_touching_other_user_locks(self) -> None:
        other_user_lock = "another-user-active-request"
        completed_request = "another-user-recent-completion"
        with (
            patch.object(ui, "_PROCESSING_LOCK", {other_user_lock}) as locks,
            patch.object(
                ui, "_RECENT_COMPLETIONS", {completed_request: 123.0}
            ) as completions,
        ):
            outputs = ui.reset_conversation()

        self.assertEqual(len(outputs), 5)
        message, display_history, audio, status, state = outputs
        self.assertEqual(message, "")
        self.assertEqual(display_history, [])
        self.assertIsNone(audio)
        self.assertIsInstance(status, str)
        self.assertTrue(status.strip())
        self.assertEqual(state["model_history"], [])
        self.assertEqual(state["display_history"], [])
        self.assertEqual(locks, {other_user_lock})
        self.assertEqual(completions, {completed_request: 123.0})

    async def test_backend_health_renders_ready_state(self) -> None:
        FakeHealthClient.payload = {
            "status": "ok",
            "config": {
                "llm_configured": True,
                "minimax_configured": True,
            },
        }
        with patch.object(ui.httpx, "AsyncClient", FakeHealthClient):
            result = await ui.backend_health()

        self.assertIsInstance(result, str)
        self.assertIn("connection-badge", result)
        self.assertIn("data-state='ready'", result)
        self.assertIn("已连接", result)

    async def test_backend_health_renders_setup_when_credentials_are_missing(self) -> None:
        FakeHealthClient.payload = {
            "status": "ok",
            "config": {
                "llm_configured": True,
                "minimax_configured": False,
            },
        }
        with patch.object(ui.httpx, "AsyncClient", FakeHealthClient):
            result = await ui.backend_health()

        self.assertIn("data-state='setup'", result)
        self.assertIn("等待配置", result)

    async def test_backend_health_renders_setup_when_backend_is_degraded(self) -> None:
        FakeHealthClient.payload = {
            "status": "degraded",
            "config": {
                "llm_configured": True,
                "minimax_configured": True,
            },
        }
        with patch.object(ui.httpx, "AsyncClient", FakeHealthClient):
            result = await ui.backend_health()

        self.assertIn("data-state='setup'", result)
        self.assertIn("等待配置", result)

    async def test_backend_health_hides_transport_error_details(self) -> None:
        secret_like_detail = "TOKEN=raw-secret-value"
        FakeHealthClient.error = RuntimeError(secret_like_detail)
        with patch.object(ui.httpx, "AsyncClient", FakeHealthClient):
            result = await ui.backend_health()

        self.assertIn("data-state='offline'", result)
        self.assertIn("未连接", result)
        self.assertNotIn(secret_like_detail, result)


if __name__ == "__main__":
    unittest.main()
