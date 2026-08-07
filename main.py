"""FastAPI entry point for the Luyao modular multi-agent runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from openai import AsyncOpenAI

from config import AppSettings, public_config
from guardrails import PersonaGuardrail
from memory import build_memory_worker
from persona import PersonaAgent
from schemas import ChatRequest, ChatResponse, HealthResponse, VoiceRequest
from service import LuyaoService, ServiceConfigurationError
from voice import VoiceRenderAgent, VoiceRenderError


logger = logging.getLogger("luyao")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def _sse(event: str, data: dict[str, Any]) -> bytes:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {encoded}\n\n".encode("utf-8")


def _build_service(settings: AppSettings) -> tuple[LuyaoService, AsyncOpenAI | None]:
    llm_client = (
        AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
        )
        if settings.llm_configured
        else None
    )
    guardrail = PersonaGuardrail()
    memory = build_memory_worker(settings, llm_client)
    persona = (
        PersonaAgent(llm_client, settings, guardrail)
        if llm_client is not None
        else None
    )
    voice = VoiceRenderAgent(settings)
    return (
        LuyaoService(
            settings=settings,
            guardrail=guardrail,
            memory=memory,
            persona=persona,
            voice=voice,
        ),
        llm_client,
    )


def create_app(
    settings: AppSettings | None = None,
    *,
    service: LuyaoService | Any | None = None,
) -> FastAPI:
    app_settings = settings or AppSettings.from_env()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        llm_client: AsyncOpenAI | None = None
        runtime_service = service
        memory_start_error: str | None = None
        if runtime_service is None:
            runtime_service, llm_client = _build_service(app_settings)
            try:
                await runtime_service.memory.start()
            except Exception as exc:
                memory_start_error = type(exc).__name__
                logger.exception("memory worker failed to start")
        app.state.service = runtime_service
        app.state.settings = app_settings
        app.state.memory_start_error = memory_start_error
        try:
            yield
        finally:
            if service is None:
                await runtime_service.memory.stop()
                await runtime_service.voice.close()
                if llm_client is not None:
                    await llm_client.close()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        lifespan=lifespan,
    )
    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(app_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Trace-ID"],
        )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        trace_id = request.headers.get("X-Trace-ID") or f"req_{uuid.uuid4().hex}"
        request.state.trace_id = trace_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled request error",
                extra={"trace_id": trace_id, "path": request.url.path},
            )
            raise
        response.headers["X-Trace-ID"] = trace_id
        logger.info(
            "request complete",
            extra={
                "trace_id": trace_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    def get_service(request: Request) -> LuyaoService:
        return request.app.state.service

    @app.exception_handler(ServiceConfigurationError)
    async def configuration_error_handler(
        request: Request, exc: ServiceConfigurationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "trace_id": getattr(request.state, "trace_id", None),
            },
        )

    @app.exception_handler(VoiceRenderError)
    async def voice_error_handler(
        request: Request, exc: VoiceRenderError
    ) -> JSONResponse:
        logger.warning(
            "voice request failed",
            extra={"trace_id": getattr(request.state, "trace_id", None)},
        )
        return JSONResponse(
            status_code=502,
            content={
                "detail": str(exc),
                "trace_id": getattr(request.state, "trace_id", None),
            },
        )

    @app.get("/health", response_model=HealthResponse)
    async def health(
        request: Request,
        runtime: LuyaoService = Depends(get_service),
    ) -> HealthResponse:
        memory_running = bool(getattr(runtime.memory, "running", False))
        degraded = (
            not app_settings.llm_configured
            or not app_settings.minimax_configured
            or bool(request.app.state.memory_start_error)
        )
        return HealthResponse(
            status="degraded" if degraded else "ok",
            version=app_settings.app_version,
            config=dict(public_config(app_settings)),
            memory_worker_running=memory_running,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat_endpoint(
        payload: ChatRequest,
        runtime: LuyaoService = Depends(get_service),
    ) -> ChatResponse:
        try:
            return await runtime.chat(payload)
        except ServiceConfigurationError:
            raise
        except Exception as exc:
            logger.exception("chat generation failed")
            raise HTTPException(
                status_code=502, detail="Upstream LLM or memory service failed"
            ) from exc

    @app.post("/api/chat/stream")
    async def stream_chat_endpoint(
        payload: ChatRequest,
        runtime: LuyaoService = Depends(get_service),
    ) -> StreamingResponse:
        async def events():
            try:
                async for event, data in runtime.stream_chat(payload):
                    yield _sse(event, data)
            except asyncio.CancelledError:
                logger.info("chat stream disconnected")
                raise
            except Exception as exc:
                logger.exception("chat stream failed")
                yield _sse(
                    "error",
                    {
                        "type": type(exc).__name__,
                        "message": "对话生成暂时失败，请稍后重试。",
                    },
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/api/voice/stream")
    async def stream_voice_endpoint(
        payload: VoiceRequest,
        runtime: LuyaoService = Depends(get_service),
    ) -> StreamingResponse:
        if not app_settings.minimax_configured:
            raise ServiceConfigurationError(
                "MINIMAX_API_KEY or MINIMAX_VOICE_ID is not configured"
            )
        return StreamingResponse(
            runtime.voice.stream_pcm(payload.text, voice_id=payload.voice_id),
            media_type="audio/pcm",
            headers={
                "Cache-Control": "no-store",
                "X-Audio-Sample-Rate": str(app_settings.audio_sample_rate),
                "X-Audio-Channels": "1",
                "X-Audio-Sample-Width": "2",
                "X-Audio-Byte-Order": "little-endian",
            },
        )

    @app.post("/api/voice")
    async def voice_endpoint(
        payload: VoiceRequest,
        runtime: LuyaoService = Depends(get_service),
    ) -> Response:
        if not app_settings.minimax_configured:
            raise ServiceConfigurationError(
                "MINIMAX_API_KEY or MINIMAX_VOICE_ID is not configured"
            )
        audio = await runtime.voice.render_wav(
            payload.text, voice_id=payload.voice_id
        )
        return Response(
            audio,
            media_type="audio/wav",
            headers={"Content-Disposition": 'inline; filename="luyao.wav"'},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
