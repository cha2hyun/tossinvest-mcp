# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.21 AS uv

FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/cha2hyun/tossinvest-mcp"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable \
    && addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /nonexistent app \
    && chown -R app:app /app

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

CMD ["uvicorn", "tossinvest_mcp.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
