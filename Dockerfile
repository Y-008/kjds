FROM python:3.12-slim AS control-plane

ARG KJDS_BUILD_COMMIT=UNKNOWN
ARG KJDS_MIGRATION_HEAD=UNKNOWN
LABEL org.opencontainers.image.revision="${KJDS_BUILD_COMMIT}" \
      io.kjds.migration.head="${KJDS_MIGRATION_HEAD}" \
      io.kjds.release.provenance.contract="kjds-release-evidence-bundle-v1"

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

FROM control-plane AS migrate
# Schema ownership belongs to this short-lived image/service only.  The
# migration principal is deliberately rejected if a runtime DSN is supplied;
# this prevents an accidental API/worker credential from being used for DDL.
CMD ["sh", "-c", "if [ -z \"${KJDS_DATABASE_URL:-}\" ]; then echo 'KJDS_DATABASE_URL is required for the one-shot migrate service' >&2; exit 64; fi; if [ -n \"${KJDS_RUNTIME_DATABASE_URL:-}\" ]; then echo 'migrate service must not receive KJDS_RUNTIME_DATABASE_URL' >&2; exit 64; fi; exec alembic upgrade head"]

FROM control-plane AS api
CMD ["uvicorn", "apps.control_plane.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM mwader/static-ffmpeg:7.1 AS ffmpeg

FROM control-plane AS media-worker
COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe
