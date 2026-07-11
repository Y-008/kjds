FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY apps ./apps
RUN pip install --no-cache-dir .
COPY migrations ./migrations

ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn apps.control_plane.api:app --host 0.0.0.0 --port 8000"]
