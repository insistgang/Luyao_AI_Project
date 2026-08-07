import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_pages import build, space_url
from scripts.sync_hf_space import prepare_bundle
from space_app import build_auth
from space_launcher import build_local_settings, write_runtime_settings


class PagesBuildTests(unittest.TestCase):
    def test_space_id_becomes_hf_space_url(self) -> None:
        self.assertEqual(
            space_url("My-User/Luyao_AI_Project"),
            "https://my-user-luyao-ai-project.hf.space",
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
                space_id="owner/Luyao_AI_Project",
            )
            self.assertEqual(
                url, "https://owner-luyao-ai-project.hf.space"
            )
            self.assertIn(url, (output / "config.js").read_text("utf-8"))
            self.assertTrue((output / ".nojekyll").exists())

    def test_rejects_non_hf_embed_url(self) -> None:
        with self.assertRaises(ValueError):
            space_url(explicit_url="https://example.com/app")


class SpaceDeploymentTests(unittest.TestCase):
    def test_space_bundle_excludes_local_secrets_and_reference_video(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            prepare_bundle(project_root, output)
            self.assertTrue((output / "Dockerfile").is_file())
            self.assertTrue((output / "README.md").is_file())
            self.assertFalse((output / "local_settings.py").exists())
            self.assertFalse((output / ".env").exists())
            self.assertFalse((output / "123.mp4").exists())

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

    def test_space_requires_access_password_by_default(self) -> None:
        with self.assertRaises(RuntimeError):
            build_auth({"SPACE_ID": "owner/space"})
        self.assertEqual(
            build_auth(
                {
                    "SPACE_ID": "owner/space",
                    "LUYAO_ACCESS_USER": "friend",
                    "LUYAO_ACCESS_PASSWORD": "test-password",
                }
            ),
            ("friend", "test-password"),
        )

    def test_local_launch_does_not_require_auth(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(build_auth())


if __name__ == "__main__":
    unittest.main()
