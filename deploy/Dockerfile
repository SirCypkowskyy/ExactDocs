# syntax=docker/dockerfile:1
# One image: FastAPI + FastMCP serving the prebuilt React UI.
# Build from the repository root:  docker build -f deploy/Dockerfile --build-arg VERSION=0.1.0 .

ARG PYTHON_VERSION=3.14
ARG NODE_VERSION=26
ARG UV_VERSION=0.13.5

# --- web UI: platform-independent static files, so build once on the native platform
FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-trixie-slim AS web
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN npm install --global "$(node -p "require('./package.json').packageManager")"
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# --- Python app: a self-contained, non-editable virtualenv
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM python:${PYTHON_VERSION}-slim-trixie AS build
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1
WORKDIR /app
ARG VERSION=0.0.0
# Packages take their version from git tags; there is no .git in the build context.
ENV UV_DYNAMIC_VERSIONING_BYPASS=${VERSION}

# Dependencies first, so source edits don't invalidate this layer.
COPY pyproject.toml uv.lock ./
COPY packages/exactdocs/pyproject.toml packages/exactdocs/README.md packages/exactdocs/
COPY packages/exactdocs-kernel/pyproject.toml packages/exactdocs-kernel/README.md packages/exactdocs-kernel/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-workspace --package exactdocs

COPY packages/ packages/
COPY --from=web /web/dist packages/exactdocs/src/exactdocs/_web
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --package exactdocs

# --- runtime
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ARG VERSION=0.0.0
LABEL org.opencontainers.image.title="ExactDocs" \
      org.opencontainers.image.description="Self-hosted, version-accurate documentation for AI coding agents" \
      org.opencontainers.image.source="https://github.com/SirCypkowskyy/ExactDocs" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}"
RUN groupadd --system --gid 10001 exactdocs \
 && useradd --system --uid 10001 --gid exactdocs --home-dir /data --no-create-home exactdocs \
 && install -d -o exactdocs -g exactdocs /data
COPY --from=build --chown=exactdocs:exactdocs /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    EXACTDOCS_HOST=0.0.0.0 \
    EXACTDOCS_PORT=3000
USER exactdocs
WORKDIR /data
VOLUME ["/data"]
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=2)"]
ENTRYPOINT ["exactdocs"]
CMD ["serve"]
