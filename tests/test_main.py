import json
import unittest

from main import _sse


class SseTests(unittest.TestCase):
    def test_sse_is_utf8_and_json(self) -> None:
        payload = _sse("text_delta", {"text": "阿雾"})
        decoded = payload.decode("utf-8")
        self.assertTrue(decoded.startswith("event: text_delta\n"))
        data_line = decoded.splitlines()[1]
        self.assertEqual(json.loads(data_line.removeprefix("data: ")), {"text": "阿雾"})


if __name__ == "__main__":
    unittest.main()

