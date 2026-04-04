FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install --upgrade pip

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install . \
    && python -c "from digital_twin.main import app; print('import ok:', app.title)"

# Cloud Run injects PORT at runtime (default 8080 for local runs).
ENV PORT=8080
EXPOSE 8080

# Shell form so $PORT is expanded when the container starts (not at image build time).
CMD ["sh", "-c", "exec python -m uvicorn digital_twin.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
