import unittest

from fastapi.testclient import TestClient

from config import AppSettings
from main import create_app


class FakeMemory:
    running = True


class FakeRuntime:
    memory = FakeMemory()


class ApiSmokeTests(unittest.TestCase):
    def test_health_starts_without_cloud_credentials(self) -> None:
        app = create_app(
            AppSettings(llm_api_key=None, minimax_api_key=None),
            service=FakeRuntime(),
        )
        with TestClient(app) as client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertFalse(response.json()["config"]["llm_configured"])


if __name__ == "__main__":
    unittest.main()
