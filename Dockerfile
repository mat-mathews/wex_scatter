# Stage 1: build dependencies
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY scatter/ scatter/
RUN uv sync --frozen --no-dev

# Stage 2: runtime
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/scatter /app/scatter

WORKDIR /workspace

ENTRYPOINT ["/app/.venv/bin/scatter"]
