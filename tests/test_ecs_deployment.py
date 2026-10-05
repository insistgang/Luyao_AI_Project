import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

import ui
from scripts.container_healthcheck import check_health, health_urls
from space_launcher import _stop_processes, build_local_settings, main


PREVIEW_ENV = {
    "LUYAO_ALLOW_UNCONFIGURED": "true",
    "LUYAO_REQUIRE_AUTH": "true",
    "LUYAO_ACCESS_PASSWORD": "unit-test-password",
}


class HttpResponse(io.BytesIO):
    status = 200


class EcsDeploymentTests(unittest.TestCase):
    def test_missing_key_still_fails_in_normal_mode(self):
        with self.assertRaises(RuntimeError):
            build_local_settings({})

    def test_preview_requires_explicit_authentication(self):
        with self.assertRaises(RuntimeError):
            build_local_settings({**PREVIEW_ENV, "LUYAO_REQUIRE_AUTH": "false"})

    def test_preview_requires_a_password(self):
        with self.assertRaises(RuntimeError):
            build_local_settings({**PREVIEW_ENV, "LUYAO_ACCESS_PASSWORD": ""})

    def test_guarded_preview_uses_an_empty_key_not_a_placeholder(self):
        config = build_local_settings(PREVIEW_ENV)
        self.assertIn('MINIMAX_API_KEY = ""', config)

    def test_public_preview_can_start_without_login_or_cloud_credentials(self):
        config = build_local_settings(
            {"LUYAO_ALLOW_UNCONFIGURED": "true", "LUYAO_ALLOW_PUBLIC": "true"}
        )
        self.assertIn('MINIMAX_API_KEY = ""', config)

    def test_public_mode_accepts_an_explicit_paid_api_key(self):
        config = build_local_settings(
            {
                "LUYAO_ALLOW_UNCONFIGURED": "true",
                "LUYAO_ALLOW_PUBLIC": "true",
                "MINIMAX_API_KEY": "test-key",
            }
        )
        self.assertIn('MINIMAX_API_KEY = "test-key"', config)

    def test_public_access_does_not_silently_enable_unconfigured_preview(self):
        with self.assertRaises(RuntimeError):
            build_local_settings({"LUYAO_ALLOW_PUBLIC": "true"})

    def test_health_uses_the_same_port_precedence_as_launcher(self):
        urls = health_urls({"PORT": "10000", "LUYAO_UI_PORT": "7860"})
        self.assertEqual(urls, ("http://127.0.0.1:8000/health", "http://127.0.0.1:7860/"))

    def test_health_checks_both_backend_and_frontend(self):
        responses = [HttpResponse(b'{"status":"ok"}'), HttpResponse(b"UI")]
        with patch("urllib.request.urlopen", side_effect=responses) as request:
            check_health({})
        self.assertEqual(request.call_count, 2)

    def test_normal_health_rejects_a_degraded_backend(self):
        with patch("urllib.request.urlopen", return_value=HttpResponse(b'{"status":"degraded"}')):
            with self.assertRaises(RuntimeError):
                check_health({})

    def test_guarded_preview_reports_live_unconfigured_service(self):
        payload = {"status": "degraded", "config": {"llm_configured": False, "minimax_configured": False}}
        responses = [HttpResponse(json.dumps(payload).encode()), HttpResponse(b"UI")]
        with patch("urllib.request.urlopen", side_effect=responses):
            check_health(PREVIEW_ENV)

    def test_public_preview_health_reports_live_unconfigured_service(self):
        payload = {"status": "degraded", "config": {"llm_configured": False, "minimax_configured": False}}
        responses = [HttpResponse(json.dumps(payload).encode()), HttpResponse(b"UI")]
        with patch("urllib.request.urlopen", side_effect=responses):
            check_health(
                {"LUYAO_ALLOW_UNCONFIGURED": "true", "LUYAO_ALLOW_PUBLIC": "true"}
            )

    def test_public_mode_health_accepts_a_ready_configured_backend(self):
        payload = {"status": "ok", "config": {"llm_configured": True, "minimax_configured": True}}
        responses = [HttpResponse(json.dumps(payload).encode()), HttpResponse(b"UI")]
        with patch("urllib.request.urlopen", side_effect=responses):
            check_health(
                {"LUYAO_ALLOW_UNCONFIGURED": "true", "LUYAO_ALLOW_PUBLIC": "true"}
            )

    def test_public_mode_health_still_rejects_a_degraded_configured_backend(self):
        payload = {"status": "degraded", "config": {"llm_configured": True, "minimax_configured": True}}
        with patch("urllib.request.urlopen", return_value=HttpResponse(json.dumps(payload).encode())):
            with self.assertRaises(RuntimeError):
                check_health(
                    {"LUYAO_ALLOW_UNCONFIGURED": "true", "LUYAO_ALLOW_PUBLIC": "true"}
                )

    def test_assets_and_launch_keep_the_reverse_proxy_prefix(self):
        with patch.dict(os.environ, {"LUYAO_ROOT_PATH": "/luyao/"}):
            self.assertTrue(ui._asset_url("luyao-avatar.png").startswith("/luyao/gradio_api/file="))
            self.assertEqual(ui.launch_options()["root_path"], "/luyao")

    def test_private_runtime_files_are_not_served_by_gradio(self):
        blocked = {Path(p).name for p in ui.launch_options()["blocked_paths"]}
        self.assertTrue({"local_settings.py", ".env.ecs", "runtime-logs", "chroma_db"} <= blocked)

    def test_both_children_are_signalled_before_waiting(self):
        frontend, backend = Mock(), Mock()
        frontend.poll.return_value = backend.poll.return_value = None

        def wait_frontend(timeout):
            self.assertTrue(backend.terminate.called)
            self.assertEqual(timeout, 5)

        frontend.wait.side_effect = wait_frontend
        _stop_processes(frontend, backend)
        backend.wait.assert_called_once_with(timeout=25)

    def test_backend_exit_ends_launcher_and_stops_frontend(self):
        backend, frontend = Mock(), Mock()
        backend.poll.return_value = 17
        frontend.poll.return_value = None
        with (
            patch("space_launcher.write_runtime_settings"),
            patch("space_launcher.wait_for_backend"),
            patch("space_launcher.signal.signal"),
            patch("space_launcher.subprocess.Popen", side_effect=[backend, frontend]),
        ):
            self.assertEqual(main(), 17)
        self.assertTrue(frontend.terminate.called)

    def test_ecs_only_exposes_loopback_and_persists_state(self):
        root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load((root / "compose.ecs.yml").read_text())
        app = config["services"]["luyao"]
        self.assertEqual(app["ports"], ["127.0.0.1:17860:7860"])
        self.assertEqual(app["environment"]["LUYAO_REQUIRE_AUTH"], "${LUYAO_REQUIRE_AUTH:-true}")
        self.assertEqual(app["environment"]["LUYAO_ALLOW_PUBLIC"], "${LUYAO_ALLOW_PUBLIC:-false}")
        self.assertEqual(app["environment"]["LUYAO_MEMORY_EXTRACTOR"], "${LUYAO_MEMORY_EXTRACTOR:-true}")
        self.assertTrue({"memories:/app/chroma_db", "runtime:/app/runtime-logs", "embeddings:/home/user/.cache/chroma"} <= set(app["volumes"]))


if __name__ == "__main__":
    unittest.main()
