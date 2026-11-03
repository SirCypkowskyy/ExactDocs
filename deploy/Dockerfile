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

# --- Python app: a self-contained, non-editable virtualenv.
# Built natively on the build platform and cross-installed for the target one (wheels for
# TARGETARCH): Python 3.14 crashes under QEMU user-mode emulation, and native is much faster.
# The venv's interpreter symlink points at /usr/local/bin/python3, present in the runtime image.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM --platform=$BUILDPLATFORM python:${PYTHON_VERSION}-slim-trixie AS build
COPY --from=uv /uv /uvx /usr/local/bin/
ARG TARGETARCH
RUN case "$TARGETARCH" in \
      amd64) echo x86_64-unknown-linux-gnu ;; \
      arm64) echo aarch64-unknown-linux-gnu ;; \
      *) echo "unsupported TARGETARCH=$TARGETARCH" >&2; exit 1 ;; \
    esac > /tmp/python-platform
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
    uv sync --locked --no-install-workspace --package exactdocs \
      --python-platform "$(cat /tmp/python-platform)"

COPY packages/ packages/
COPY --from=web /web/dist packages/exactdocs/src/exactdocs/_web
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --package exactdocs \
      --python-platform "$(cat /tmp/python-platform)"
RUN mkdir /data

# --- runtime: no RUN instructions, so a foreign-arch image never executes anything at build time
# (the runner is ARM64; amd64 needs no emulation). The user is numeric: no /etc/passwd edits.
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ARG VERSION=0.0.0
LABEL org.opencontainers.image.title="ExactDocs" \
      org.opencontainers.image.description="Self-hosted, version-accurate documentation for AI coding agents" \
      org.opencontainers.image.source="https://github.com/SirCypkowskyy/ExactDocs" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}"
COPY --from=build --chown=10001:10001 /data /data
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    HOME=/data \
    PYTHONUNBUFFERED=1 \
    EXACTDOCS_HOST=0.0.0.0 \
    EXACTDOCS_DATA_DIR=/data \
    EXACTDOCS_PORT=3000
USER 10001:10001
WORKDIR /data
VOLUME ["/data"]
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=2)"]
ENTRYPOINT ["exactdocs"]
CMD ["serve"]
