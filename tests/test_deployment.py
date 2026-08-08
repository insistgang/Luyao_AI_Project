import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_pages import app_url, build
from space_app import build_auth
from space_launcher import (
    build_local_settings,
    resolve_ui_port,
    write_runtime_settings,
)


class PagesBuildTests(unittest.TestCase):
    def test_normalizes_render_url(self) -> None:
        self.assertEqual(
            app_url(" https://luyao-ai-project.onrender.com/ "),
            "https://luyao-ai-project.onrender.com",
        )

    def test_pages_artifact_contains_generated_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "site"
            output = root / "output"
            source.mkdir()
            (source / "index.html").write_text("ok", encoding="utf-8")
            url = build(
                source,
                output,
                explicit_url="https://luyao-ai-project.onrender.com",
            )
            self.assertEqual(
                url, "https://luyao-ai-project.onrender.com"
            )
            config = (output / "config.js").read_text("utf-8")
            self.assertIn('"appUrl":', config)
            self.assertIn(url, config)
            self.assertTrue((output / ".nojekyll").exists())

    def test_empty_url_builds_setup_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "site"
            output = root / "output"
            source.mkdir()
            (source / "index.html").write_text("ok", encoding="utf-8")
            self.assertEqual(build(source, output), "")
            self.assertIn(
                '"appUrl": ""',
                (output / "config.js").read_text("utf-8"),
            )

    def test_rejects_unsafe_embed_urls(self) -> None:
        unsafe_urls = (
            "http://luyao-ai-project.onrender.com",
            "https://user:password@example.com",
            "https://example.com/?token=secret",
            "https://example.com/#fragment",
        )
        for url in unsafe_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                app_url(url)


class HostedRuntimeTests(unittest.TestCase):
    def test_runtime_settings_are_generated_without_logging_secret(self) -> None:
        settings = build_local_settings({"MINIMAX_API_KEY": "test-key"})
        self.assertIn('MINIMAX_API_KEY = "test-key"', settings)
        self.assertIn('MINIMAX_CHAT_MODEL = "abab6.5s-chat"', settings)
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "local_settings.py"
            write_runtime_settings(
                target, {"MINIMAX_API_KEY": "test-key"}
            )
            self.assertTrue(target.is_file())

    def test_managed_host_requires_access_password_by_default(self) -> None:
        for marker in (
            {"LUYAO_REQUIRE_AUTH": "true"},
            {"RENDER": "true"},
            {"SPACE_ID": "legacy/space"},
        ):
            with self.subTest(marker=marker), self.assertRaises(RuntimeError):
                build_auth(marker)
        self.assertEqual(
            build_auth(
                {
                    "LUYAO_REQUIRE_AUTH": "true",
                    "LUYAO_ACCESS_USER": "friend",
                    "LUYAO_ACCESS_PASSWORD": "test-password",
                }
            ),
            ("friend", "test-password"),
        )

    def test_local_launch_does_not_require_auth(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(build_auth())

    def test_render_port_is_used_unless_explicitly_overridden(self) -> None:
        self.assertEqual(resolve_ui_port({"PORT": "10000"}), 10000)
        self.assertEqual(
            resolve_ui_port({"PORT": "10000", "LUYAO_UI_PORT": "7861"}),
            7861,
        )

    def test_rejects_invalid_public_port(self) -> None:
        for value in ("not-a-port", "0", "65536"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                resolve_ui_port({"PORT": value})


class RenderBlueprintTests(unittest.TestCase):
    def test_blueprint_uses_free_docker_service_and_secret_prompts(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        blueprint = (project_root / "render.yaml").read_text("utf-8")
        self.assertIn("runtime: docker", blueprint)
        self.assertIn("plan: free", blueprint)
        self.assertIn("region: singapore", blueprint)
        self.assertIn("healthCheckPath: /", blueprint)
        self.assertIn("key: MINIMAX_API_KEY\n        sync: false", blueprint)
        self.assertIn(
            "key: LUYAO_ACCESS_PASSWORD\n        sync: false", blueprint
        )

    def test_pages_workflow_no_longer_deploys_hugging_face(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        workflow = (
            project_root / ".github" / "workflows" / "deploy.yml"
        ).read_text("utf-8")
        self.assertIn("LUYAO_APP_URL", workflow)
        self.assertNotIn("HF_TOKEN", workflow)
        self.assertNotIn("deploy-space", workflow)


if __name__ == "__main__":
    unittest.main()
