FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GRADIO_ANALYTICS_ENABLED=False \
    LUYAO_UI_HOST=0.0.0.0 \
    LUYAO_API_URL=http://127.0.0.1:8000

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 user

WORKDIR /app

COPY --chown=user:user requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY --chown=user:user config.py guardrails.py main.py memory.py persona.py schemas.py service.py ui.py voice.py /app/
COPY --chown=user:user space_app.py space_launcher.py /app/

RUN mkdir -p /app/chroma_db && chown -R user:user /app

USER user
EXPOSE 7860 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.getenv('PORT') or os.getenv('LUYAO_UI_PORT') or '7860'; urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=3)"

CMD ["python", "space_launcher.py"]
