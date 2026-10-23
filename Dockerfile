# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM python:3.12-slim-trixie

LABEL org.opencontainers.image.source="https://github.com/cha2hyun/tossinvest-mcp"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/

# FastMCP uses OS trust; pip also bundles its own CA certificates. Refresh both
# stores for the October 2026 eMudhra incident, including the AAA cross-sign.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge 20250419+deb13u1 \
    && rm -rf /var/lib/apt/lists/* \
    && uv pip install --system --upgrade 'pip>=26.2.2,<27'

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
  CMD ["python", "-c", "import os, urllib.request; port=os.getenv('MCP_PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3)"]

CMD ["tossinvest-mcp"]
