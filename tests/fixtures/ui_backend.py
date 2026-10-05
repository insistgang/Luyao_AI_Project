"""Loopback-only UI test fixture. Never calls a model or stores real memory."""

import argparse
import io
import json
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


state = {"mode": "ready", "chat_calls": 0, "voice_calls": 0, "health_delay": 0, "last_history": []}
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            time.sleep(state["health_delay"])
            ready = state["mode"] in {"ready", "limited"}
            payload = {"status": "ok" if state["mode"] == "ready" else "degraded", "config": {"llm_configured": ready, "minimax_configured": ready}}
            self.respond(200, json.dumps(payload).encode())
        elif self.path == "/_test/state":
            self.respond(200, json.dumps(state).encode())
        else:
            self.respond(404, b"{}")

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/_test/mode":
            assert payload["mode"] in {"ready", "setup", "limited"}
            with lock:
                state.update(mode=payload["mode"], chat_calls=0, voice_calls=0, last_history=[], health_delay=float(payload.get("health_delay", 0)))
            self.respond(200, b"{}")
            return
        if state["mode"] == "setup":
            self.respond(503, b'{"detail":"test backend is not configured"}')
            return
        if self.path == "/api/chat/stream":
            with lock:
                state["chat_calls"] += 1
                state["last_history"] = payload.get("chat_history", [])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.end_headers()
            events = [("meta", {"trace_id": "ui-local-test"})]
            events.extend(("text_delta", {"text": text}) for text in ("收到。", "[pause] 这是本机交互测试。"))
            events.append(("done", {"raw_text": "收到。[pause] 这是本机交互测试。"}))
            try:
                for event, data in events:
                    time.sleep(self.server.delay)
                    self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path == "/api/voice":
            with lock:
                state["voice_calls"] += 1
            output = io.BytesIO()
            with wave.open(output, "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(32000)
                audio.writeframes(b"\0\0" * 6400)
            self.respond(200, output.getvalue(), "audio/wav")
        else:
            self.respond(404, b"{}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18001)
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.delay = args.delay
    print(f"Local-only UI fixture: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
