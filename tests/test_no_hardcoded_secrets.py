import re
import unittest
from pathlib import Path


class SecretRegressionTests(unittest.TestCase):
    def test_shared_python_sources_have_no_secret_literals(self) -> None:
        project = Path(__file__).resolve().parents[1]
        secret_pattern = re.compile(r"sk-cp-[A-Za-z0-9_-]{20,}")
        offenders = []
        for source in project.glob("*.py"):
            if source.name == "local_settings.py":
                continue
            if secret_pattern.search(
                source.read_text(encoding="utf-8")
            ):
                offenders.append(source.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

