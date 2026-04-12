FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY uvicorn_logging.json ./uvicorn_logging.json

RUN uv sync --frozen --no-dev \
    && uv run python -c "from digital_twin.main import app; import digital_twin.run_session_digest; print('import ok:', app.title)"

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec uv run python -m uvicorn digital_twin.main:app --host 0.0.0.0 --port ${PORT:-8080} --log-config /app/uvicorn_logging.json"]
