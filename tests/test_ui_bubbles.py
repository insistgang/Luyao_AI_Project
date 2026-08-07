import unittest

from ui import _clean_history, _split_into_bubbles


class UiBubbleRegressionTests(unittest.TestCase):
    def test_tagged_reply_becomes_multiple_clean_bubbles(self) -> None:
        bubbles = _split_into_bubbles(
            "[sigh] 送一台白色基础款拍立得吧。"
            "[pause] [whisper] 那是她一直想要的。"
        )
        self.assertEqual(
            bubbles,
            [
                "送一台白色基础款拍立得吧。",
                "那是她一直想要的。",
            ],
        )
        self.assertNotIn("[", "".join(bubbles))

    def test_visual_bubbles_merge_back_into_model_history(self) -> None:
        history = _clean_history(
            [
                {"role": "user", "content": "你怎么知道？"},
                {"role": "assistant", "content": "因为你说过很多遍。"},
                {"role": "assistant", "content": "阿雾，我都记得。"},
            ]
        )
        self.assertEqual(len(history), 2)
        self.assertIn("阿雾，我都记得。", history[1]["content"])


if __name__ == "__main__":
    unittest.main()

