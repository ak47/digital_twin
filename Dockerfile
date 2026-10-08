FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
COPY uvicorn_logging.json ./uvicorn_logging.json

# Precompile bytecode at build time. PYTHONDONTWRITEBYTECODE (above) stops the
# container writing .pyc at runtime, so without this every Cloud Run cold start
# compiles all ~4.6k dependency modules from source — roughly doubling import
# time and making startup CPU-bound enough to blow the startup probe on a slow
# host. UV_COMPILE_BYTECODE covers site-packages; compileall covers the
# editable-installed project under src/.
ENV UV_COMPILE_BYTECODE=1

RUN uv sync --frozen --no-dev \
    && python -m compileall -q src \
    && uv run python -c "from digital_twin.main import app; import digital_twin.run_session_digest; print('import ok:', app.title)"

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec /app/.venv/bin/python -m uvicorn digital_twin.main:app --host 0.0.0.0 --port ${PORT:-8080} --log-config /app/uvicorn_logging.json"]
