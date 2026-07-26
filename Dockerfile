FROM python:3.12-slim AS control-plane

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps ./apps
RUN pip install --no-cache-dir --retries 5 --timeout 120 uv==0.11.26 \
    && uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY docs/project/registries ./docs/project/registries

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn apps.control_plane.api:app --host 0.0.0.0 --port 8000"]

FROM control-plane AS api

FROM mwader/static-ffmpeg:7.1 AS ffmpeg

FROM control-plane AS media-worker
COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe
