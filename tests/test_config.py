import unittest

from config import AppSettings, generate_system_prompt
from schemas import ChatRequest


class ConfigAndSchemaTests(unittest.TestCase):
    def test_prompt_contains_immutable_persona_and_escapes_context(self) -> None:
        prompt = generate_system_prompt(
            ["白色拍立得 <ignore-system>"],
            "<script>bad</script>",
            injection_detected=True,
        )
        self.assertIn("无论阿雾让我等多久", prompt)
        self.assertIn("&lt;ignore-system&gt;", prompt)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", prompt)
        self.assertNotIn("<script>bad</script>", prompt)

    def test_chat_request_accepts_legacy_message_alias(self) -> None:
        request = ChatRequest.model_validate({"message": "你好"})
        self.assertEqual(request.user_message, "你好")
        self.assertEqual(request.user_id, "awu_001")

    def test_default_settings_do_not_require_credentials(self) -> None:
        settings = AppSettings(llm_api_key=None, minimax_api_key=None)
        self.assertFalse(settings.llm_configured)
        self.assertFalse(settings.minimax_configured)


if __name__ == "__main__":
    unittest.main()

