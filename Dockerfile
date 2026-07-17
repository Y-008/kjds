FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps ./apps
RUN pip install --no-cache-dir uv==0.11.26 && uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn apps.control_plane.api:app --host 0.0.0.0 --port 8000"]
