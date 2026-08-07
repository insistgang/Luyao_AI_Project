import unittest

import ui


class UiSmokeTests(unittest.TestCase):
    def test_gradio_demo_builds(self) -> None:
        self.assertIsNotNone(ui.demo)
        self.assertEqual(ui.BACKEND_URL, ui.BACKEND_URL.rstrip("/"))

    def test_chatbot_renders_consecutive_replies_as_separate_bubbles(self) -> None:
        config = ui.demo.get_config_file()
        chatbot = next(
            component
            for component in config["components"]
            if component["type"] == "chatbot"
        )
        self.assertFalse(chatbot["props"]["group_consecutive_messages"])


if __name__ == "__main__":
    unittest.main()

