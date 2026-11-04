# syntax=docker/dockerfile:1
# One image: FastAPI + FastMCP serving the prebuilt React UI.
# Build from the repository root:  docker build -f deploy/Dockerfile --build-arg VERSION=0.1.0 .
#
# Layers go from "changes rarely" to "changes every commit", so a source-only edit rebuilds only
# the last steps of each stage:
#   web      pnpm version -> pnpm-lock.yaml (pnpm fetch) -> manifests (install --offline) -> sources
#   python   uv.lock (exported requirements, hashes) -> workspace sources + UI -> VERSION
#
# Hardening: base images are pinned by digest (Dependabot, `docker` ecosystem on /deploy, bumps
# tag and digest together; the FROM lines are literal for that reason); the runtime holds only
# git, openssh-client, ca-certificates and tini; no pip, no setuid/setgid files; it runs as
# UID 10001 with an application tree that UID cannot write, so it works with
#   docker run --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges ...
# with /data (the volume) as the only writable path.
#
# Secrets: none enter the build. The only build arguments are VERSION, REVISION and CREATED
# (metadata), PNPM_VERSION and TARGETARCH. Never add a token or key as an ARG or ENV: both stay
# readable in the image history. Git credentials are stored by the app in /data at run time.

# --- web UI: platform-independent static files, so build once on the native platform
FROM --platform=$BUILDPLATFORM node:26-trixie-slim@sha256:e4db4c914bf8ad241bd24804fc25d272d89bad97e68cdc8a1414862790a02c39 AS web
# Keep equal to "packageManager" in web/package.json (checked below).
ARG PNPM_VERSION=12.16.1
RUN npm install --global "pnpm@${PNPM_VERSION}"
WORKDIR /web
# Download every package of the lockfile (and its pnpmfile, whose checksum the lockfile records)
# into a store that stays in the layer: the cache mount
# speeds up a changed lockfile, but a CI runner restoring layers has no mount content.
COPY web/pnpm-lock.yaml web/.pnpmfile.cjs ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store,sharing=locked \
    pnpm fetch && cp -a /root/.local/share/pnpm/store /pnpm-store
COPY web/package.json web/pnpm-workspace.yaml ./
RUN test "$(node -p "require('./package.json').packageManager")" = "pnpm@${PNPM_VERSION}" \
    || { echo "PNPM_VERSION must equal packageManager in web/package.json" >&2; exit 1; }; \
    pnpm install --prefer-offline --frozen-lockfile --store-dir /pnpm-store
COPY web/ ./
RUN pnpm build

# --- Python app: a self-contained, non-editable virtualenv.
# Built natively on the build platform and cross-installed for the target one (wheels for
# TARGETARCH): Python 3.14 crashes under QEMU user-mode emulation, and native is much faster.
# The venv's interpreter symlink points at /usr/local/bin/python3, present in the runtime image.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv
FROM --platform=$BUILDPLATFORM python:3.14-slim-trixie@sha256:930e1abba7c4e8f96ed93e8012c35d174d7732752731bbd5e8e757d7ec6f3966 AS base
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

# The third-party requirements, pinned and hashed, from uv.lock. A stage of its own so that the
# layer below is keyed on the exported text (COPY compares content): editing a pyproject.toml
# or README without touching dependencies leaves that text, and the layer, unchanged.
FROM base AS export
COPY pyproject.toml uv.lock ./
COPY packages/exactdocs/pyproject.toml packages/exactdocs/
COPY packages/exactdocs-kernel/pyproject.toml packages/exactdocs-kernel/
RUN uv export --frozen --no-emit-workspace --no-dev --package exactdocs \
      --no-header --no-annotate --output-file /requirements.txt

FROM base AS build
COPY --from=export /requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv venv /app/.venv \
    && VIRTUAL_ENV=/app/.venv uv pip install --no-deps -r /tmp/requirements.txt \
      --python-platform "$(cat /tmp/python-platform)"

# Only what the wheels need: packages/*/src, pyproject.toml, README.md (.dockerignore drops the rest).
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY --from=web /web/dist packages/exactdocs/src/exactdocs/_web
# Packages take their version from git tags; there is no .git in the build context.
ARG VERSION=0.0.0
ENV UV_DYNAMIC_VERSIONING_BYPASS=${VERSION}
# --refresh-package: uv's cache key for a local package ignores the VERSION environment variable,
# so a warm cache mount would hand back the wheel built for the previous version.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-editable --package exactdocs \
      --refresh-package exactdocs --refresh-package exactdocs-kernel \
      --python-platform "$(cat /tmp/python-platform)"
RUN mkdir /data

# --- runtime. apt needs RUN, so on the other architecture this stage runs under QEMU (binfmt
# is installed on the runners, see deploy/runners/create-vms.sh); only apt-get, dpkg, rm and find run
# there, never Python (which crashes under QEMU).
FROM python:3.14-slim-trixie@sha256:930e1abba7c4e8f96ed93e8012c35d174d7732752731bbd5e8e757d7ec6f3966 AS runtime
# Debian package versions are not pinned (hadolint DL3008): security fixes arrive with each build.
# git and openssh-client are for the importer, tini is PID 1 (reaps git children, forwards signals).
# git depends on the full Perl (50 MB) only for scripts the importer never runs (git svn, send-email,
# add -p, ...): purge it. perl-base stays, Debian needs it. (Names are those of trixie: dpkg only
# warns when one is not installed, so after a Debian bump check the image size in the CI log.)
# ssh refuses to run for a uid without a passwd entry, hence the exactdocs user (10001).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git openssh-client tini \
    && dpkg --purge --force-depends perl perl-modules-5.40 libperl5.40 liberror-perl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.14/ensurepip /usr/local/lib/python3.14/site-packages/pip* \
      /usr/local/lib/python3.14/site-packages/setuptools* /usr/local/bin/pip* \
    && find / -xdev -perm /6000 -type f -exec chmod a-s {} + \
    && echo 'exactdocs:x:10001:' >> /etc/group \
    && echo 'exactdocs:x:10001:10001::/data:/usr/sbin/nologin' >> /etc/passwd
COPY --from=build --chown=10001:10001 /data /data
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    HOME=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EXACTDOCS_HOST=0.0.0.0 \
    EXACTDOCS_DATA_DIR=/data \
    EXACTDOCS_PORT=3000
USER 10001:10001
WORKDIR /data
VOLUME ["/data"]
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=2)"]
ENTRYPOINT ["tini", "--", "exactdocs"]
CMD ["serve"]
# Metadata last: it changes on every build and must not invalidate the layers above.
ARG VERSION=0.0.0
ARG REVISION=unknown
ARG CREATED=unknown
LABEL org.opencontainers.image.title="ExactDocs" \
      org.opencontainers.image.description="Self-hosted, version-accurate documentation for AI coding agents" \
      org.opencontainers.image.source="https://github.com/SirCypkowskyy/ExactDocs" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}"
