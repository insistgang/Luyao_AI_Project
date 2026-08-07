from fastapi.testclient import TestClient
from main import app

def test_fresh_app():
    with TestClient(app) as client:
        res_voice = client.post(
            "/api/voice",
            json={"text": "[whisper] 你好，阿雾 [pause]"}
        )
        print("Voice status:", res_voice.status_code, "WAV bytes:", len(res_voice.content))
        assert res_voice.status_code == 200
        assert len(res_voice.content) > 1000
        print("✅ ALL TESTS PASSED!")

if __name__ == "__main__":
    test_fresh_app()
