FROM python:3.12-slim
ARG APT_MIRROR=http://deb.debian.org
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GRADIO_ANALYTICS_ENABLED=False \
    LUYAO_UI_HOST=0.0.0.0 \
    LUYAO_API_URL=http://127.0.0.1:8000

RUN sed -i "s#http://deb.debian.org#${APT_MIRROR%/}#g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 user

WORKDIR /app

COPY --chown=user:user requirements.lock /app/requirements.lock
RUN python -m pip install --index-url "$PIP_INDEX_URL" --upgrade pip \
    && python -m pip install --index-url "$PIP_INDEX_URL" -r /app/requirements.lock

COPY --chown=user:user config.py guardrails.py main.py memory.py persona.py schemas.py service.py ui.py voice.py /app/
COPY --chown=user:user space_app.py space_launcher.py /app/
COPY --chown=user:user assets/ui /app/assets/ui
COPY --chown=user:user scripts/container_healthcheck.py /app/scripts/container_healthcheck.py

RUN mkdir -p /app/chroma_db /app/runtime-logs /home/user/.cache/chroma \
    && chown -R user:user /app /home/user/.cache

USER user
EXPOSE 7860 10000

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD ["python", "-m", "scripts.container_healthcheck"]

CMD ["python", "space_launcher.py"]
