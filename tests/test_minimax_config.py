import unittest
from unittest.mock import patch

import local_settings

from config import AppSettings


class UnifiedMiniMaxConfigTests(unittest.TestCase):
    def test_local_file_configures_chat_and_speech(self) -> None:
        with (
            patch.object(
                local_settings, "MINIMAX_API_KEY", "test-key"
            ),
            patch.object(
                local_settings,
                "MINIMAX_API_HOST",
                "https://api.minimaxi.com",
            ),
            patch.object(
                local_settings,
                "MINIMAX_CHAT_MODEL",
                "MiniMax-M2.7",
            ),
        ):
            settings = AppSettings.from_env()

        self.assertEqual(settings.llm_api_key, "test-key")
        self.assertEqual(settings.minimax_api_key, "test-key")
        self.assertEqual(
            settings.llm_base_url, "https://api.minimaxi.com/v1"
        )
        self.assertEqual(settings.llm_model, "MiniMax-M2.7")
        self.assertTrue(settings.llm_configured)
        self.assertTrue(settings.minimax_configured)

    def test_environment_key_is_not_required(self) -> None:
        with patch.object(
            local_settings, "MINIMAX_API_KEY", "local-only-key"
        ):
            settings = AppSettings.from_env()
        self.assertEqual(settings.minimax_api_key, "local-only-key")


if __name__ == "__main__":
    unittest.main()

