FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock Readme.md ./
RUN uv sync --frozen --no-dev
COPY downloader/ downloader/
COPY --from=web /app/web/dist web/dist
ENV DATA_DIR=/data DOWNLOAD_DIR=/downloads
VOLUME ["/data", "/downloads"]
EXPOSE 8000
CMD ["uvicorn", "downloader.app:app", "--host", "0.0.0.0", "--port", "8000"]
