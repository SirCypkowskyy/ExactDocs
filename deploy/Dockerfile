# syntax=docker/dockerfile:1
# FastAPI + FastMCP serving the prebuilt React UI, in three variants (build targets, #246):
#   base   BM25 only, model-free (RUN-02); the default target       ghcr.io/...:<v>
#   ai     exactdocs[ai]: hosted and self-hosted model providers     ghcr.io/...:<v>-ai
#   local  exactdocs[ai,local] plus the two default local models,    ghcr.io/...:<v>-local
#          pulled at their pinned revisions into /opt/exactdocs/models (read-only)
# Build from the repository root:
#   docker build -f deploy/Dockerfile --build-arg VERSION=0.1.0 [--target ai|local] .
# Size budgets per variant: deploy/check_artifacts.py and docs/releasing.md.
#
# Layers go from "changes rarely" to "changes every commit", so a source-only edit rebuilds only
# the last steps of each stage:
#   web      pnpm version -> pnpm-lock.yaml (pnpm fetch) -> manifests (install --prefer-offline) -> sources
#   python   uv.lock (exported requirements, hashes) -> [ai] -> [local] -> workspace sources + UI -> VERSION
#   models   (local only) the default models, from a cache mount once pulled
#
# Hardening: base images are pinned by digest (Dependabot, `docker` ecosystem on /deploy, bumps
# tag and digest together; the FROM lines are literal for that reason); the runtime holds only
# git, openssh-client, ca-certificates and tini; no pip, no setuid/setgid files; it runs as
# UID 10001 with an application tree that UID cannot write, so it works with
#   docker run --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges ...
# with /data (the volume) as the only writable path.
#
# Secrets: none enter the build. The only build arguments are VERSION, REVISION and CREATED
# (metadata), PNPM_VERSION and DEBIAN_REFRESH (the package-index cache key). Never add a token or key as an ARG or ENV: both stay
# readable in the image history. Git credentials are stored by the app in /data at run time.

# --- web UI: platform-independent static files, so build once on the native platform
FROM --platform=$BUILDPLATFORM node:26-trixie-slim@sha256:e4db4c914bf8ad241bd24804fc25d272d89bad97e68cdc8a1414862790a02c39 AS web
# Keep equal to "packageManager" in web/package.json (checked below).
ARG PNPM_VERSION=12.16.1
RUN npm install --global "pnpm@${PNPM_VERSION}"
WORKDIR /web
# Download every package of the lockfile (and its pnpmfile, whose checksum the lockfile records)
# into a store that stays in the layer: the cache mount
# speeds up a changed lockfile, but a builder restoring layers from a remote cache has no mount content.
COPY web/pnpm-lock.yaml web/.pnpmfile.cjs ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store,sharing=locked \
    pnpm fetch && cp -a /root/.local/share/pnpm/store /pnpm-store
COPY web/package.json web/pnpm-workspace.yaml ./
RUN test "$(node -p "require('./package.json').packageManager")" = "pnpm@${PNPM_VERSION}" \
    || { echo "PNPM_VERSION must equal packageManager in web/package.json" >&2; exit 1; }; \
    # --prefer-offline, not --offline: pnpm 12's minimumReleaseAge check needs registry metadata
    # for every lockfile entry (also other platforms' packages that `pnpm fetch` skips), so
    # --offline fails with ERR_PNPM_NO_OFFLINE_META. No package is downloaded (all come from the
    # store), but the build needs registry access: this layer is not hermetic.
    pnpm install --prefer-offline --frozen-lockfile --store-dir /pnpm-store
COPY web/ ./
RUN pnpm build

# --- Python app: a self-contained, non-editable virtualenv.
# Built natively on the build platform and cross-installed for the target one (wheels for
# TARGETARCH): Python 3.14 crashes under QEMU user-mode emulation, and native is much faster.
# The venv's interpreter symlink points at /usr/local/bin/python3, present in the runtime image.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv
FROM --platform=$BUILDPLATFORM python:3.14-slim-trixie@sha256:f1b121a95d6295f7291a0fda8280f747efd657bd055e7c1f156936ed2dc5a112 AS builder
COPY --from=uv /uv /uvx /usr/local/bin/
ARG TARGETARCH
RUN case "$TARGETARCH" in \
      amd64) echo x86_64-unknown-linux-gnu ;; \
      arm64) echo aarch64-unknown-linux-gnu ;; \
      *) echo "unsupported TARGETARCH=$TARGETARCH" >&2; exit 1 ;; \
    esac > /tmp/python-platform \
    && mkdir /data
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1
WORKDIR /app

# The third-party requirements, pinned and hashed, from uv.lock: the default set and the sets
# with the extras of each variant. A stage of its own so that the layers below are keyed on the
# exported text (COPY compares content): editing a pyproject.toml or README without touching
# dependencies leaves that text, and the layers, unchanged.
FROM builder AS export
COPY pyproject.toml uv.lock ./
COPY packages/exactdocs/pyproject.toml packages/exactdocs/
COPY packages/exactdocs-kernel/pyproject.toml packages/exactdocs-kernel/
RUN uv export --frozen --no-emit-workspace --no-dev --package exactdocs \
      --no-header --no-annotate --output-file /requirements.txt \
    && uv export --frozen --no-emit-workspace --no-dev --package exactdocs --extra ai \
      --no-header --no-annotate --output-file /requirements-ai.txt \
    && uv export --frozen --no-emit-workspace --no-dev --package exactdocs --extra ai --extra local \
      --no-header --no-annotate --output-file /requirements-ai-local.txt

# The virtualenv's third-party packages, one stage per variant, each on top of the smaller one:
# uv skips what is installed already, so [ai] adds only its own packages.
FROM builder AS deps
COPY --from=export /requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv venv /app/.venv \
    && VIRTUAL_ENV=/app/.venv uv pip install --no-deps -r /tmp/requirements.txt \
      --python-platform "$(cat /tmp/python-platform)"

FROM deps AS deps-ai
COPY --from=export /requirements-ai.txt /tmp/requirements-ai.txt
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    VIRTUAL_ENV=/app/.venv uv pip install --no-deps -r /tmp/requirements-ai.txt \
      --python-platform "$(cat /tmp/python-platform)"

FROM deps-ai AS deps-local
COPY --from=export /requirements-ai-local.txt /tmp/requirements-ai-local.txt
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    VIRTUAL_ENV=/app/.venv uv pip install --no-deps -r /tmp/requirements-ai-local.txt \
      --python-platform "$(cat /tmp/python-platform)"

# Only what the wheels need: packages/*/src, pyproject.toml, README.md (.dockerignore drops the
# rest), and the UI. One stage, copied into each variant's build.
FROM scratch AS sources
COPY pyproject.toml uv.lock /app/
COPY packages/ /app/packages/
COPY --from=web /web/dist /app/packages/exactdocs/src/exactdocs/_web

# The workspace packages into each variant's virtualenv. `uv sync` is exact: the venv ends up with
# the locked set of that variant and nothing else.
# Packages take their version from git tags; there is no .git in the build context.
# --refresh-package: uv's cache key for a local package ignores the VERSION environment variable,
# so a warm cache mount would hand back the wheel built for the previous version.
FROM deps AS build
COPY --from=sources /app/ ./
ARG VERSION=0.0.0
ENV UV_DYNAMIC_VERSIONING_BYPASS=${VERSION}
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-editable --package exactdocs \
      --refresh-package exactdocs --refresh-package exactdocs-kernel \
      --python-platform "$(cat /tmp/python-platform)"

FROM deps-ai AS build-ai
COPY --from=sources /app/ ./
ARG VERSION=0.0.0
ENV UV_DYNAMIC_VERSIONING_BYPASS=${VERSION}
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-editable --package exactdocs --extra ai \
      --refresh-package exactdocs --refresh-package exactdocs-kernel \
      --python-platform "$(cat /tmp/python-platform)"

FROM deps-local AS build-local
COPY --from=sources /app/ ./
ARG VERSION=0.0.0
ENV UV_DYNAMIC_VERSIONING_BYPASS=${VERSION}
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-editable --package exactdocs --extra ai --extra local \
      --refresh-package exactdocs --refresh-package exactdocs-kernel \
      --python-platform "$(cat /tmp/python-platform)"

# --- the default local models, for the `local` target only. Model files are the same on every
# platform, so this runs natively, once, with a virtualenv for the build platform (the variant's
# own venv may be for the other architecture). `exactdocs models pull` fetches each default at
# its pinned Hub revision (PINNED_MODEL_REVISIONS) into a cache mount and skips a model already
# there at that revision, so a rebuild contacts no Hub; only the default models are copied out.
FROM builder AS models
COPY --from=export /requirements-ai-local.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv venv /models-venv \
    && VIRTUAL_ENV=/models-venv uv pip install --no-deps -r /tmp/requirements.txt
COPY --from=sources /app/ ./
ARG VERSION=0.0.0
ENV UV_DYNAMIC_VERSIONING_BYPASS=${VERSION}
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    VIRTUAL_ENV=/models-venv uv pip install --no-deps ./packages/exactdocs-kernel ./packages/exactdocs
RUN --mount=type=cache,target=/models-cache,id=exactdocs-models,sharing=locked \
    EXACTDOCS_MODELS_DIR=/models-cache /models-venv/bin/exactdocs models pull \
    && /models-venv/bin/python -c 'import shutil; from exactdocs.bootstrap.models_pull import default_models; [shutil.copytree(f"/models-cache/{m}", f"/opt/exactdocs/models/{m}") for m in default_models()]' \
    && chmod -R a+rX,go-w /opt/exactdocs/models

# --- Debian package indexes for the runtime. The trixie apt verifies them with sqv, which fails
# under QEMU ("No good signature"), so this native stage runs `apt-get update` (adding the target
# architecture) and the runtime stage installs from these lists without updating.
FROM --platform=$BUILDPLATFORM python:3.14-slim-trixie@sha256:f1b121a95d6295f7291a0fda8280f747efd657bd055e7c1f156936ed2dc5a112 AS apt-lists
ARG TARGETARCH
# A cached layer keeps the package set of the first build; the release passes a new value (the
# date) so that it installs the current Debian security updates.
ARG DEBIAN_REFRESH=none
RUN : "$DEBIAN_REFRESH" \
    && dpkg --add-architecture "$TARGETARCH" \
    && apt-get update

# --- runtime. apt needs RUN, so on the other architecture this stage runs under QEMU (binfmt
# is installed on the runners, see deploy/runners/create-vms.sh); only apt-get, dpkg, rm and find run
# there, never Python (which crashes under QEMU).
FROM python:3.14-slim-trixie@sha256:f1b121a95d6295f7291a0fda8280f747efd657bd055e7c1f156936ed2dc5a112 AS runtime-tools
# Debian package versions are not pinned (hadolint DL3008): security fixes arrive with each build.
# git and openssh-client are for the importer, tini is PID 1 (reaps git children, forwards signals).
# git depends on the full Perl (50 MB) only for scripts the importer never runs (git svn, send-email,
# add -p, ...): purge it. perl-base stays, Debian needs it. The dependency state is left
# intentionally broken (git-core still "depends" on perl): never run `apt-get install -f` or
# `dpkg --audit` fixes here. (Names are those of trixie: dpkg only warns when one is not
# installed, so after a Debian bump check the image size in the CI log.)
# ssh refuses to run for a uid without a passwd entry, hence the exactdocs user (10001).
# zlib1g comes with the base image, so the install above would leave it at the base's +b1, which
# has HIGH CVE-2026-76844 and CVE-2026-85091 (#275). No python:3.14-slim-trixie build ships the
# fixed +deb13u1 (trixie-security) yet: upgrade it here, and drop this once a new base digest has it.
RUN --mount=type=bind,from=apt-lists,source=/var/lib/apt/lists,target=/var/lib/apt/lists,rw \
    apt-get install -y --no-install-recommends ca-certificates git openssh-client tini \
    && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
    && dpkg --purge --force-depends perl perl-modules-5.40 libperl5.40 liberror-perl \
    && rm -rf /usr/local/lib/python3.14/ensurepip /usr/local/lib/python3.14/site-packages/pip* \
      /usr/local/lib/python3.14/site-packages/setuptools* /usr/local/bin/pip* \
    && find / -xdev -perm /6000 -type f -exec chmod a-s {} + \
    && echo 'exactdocs:x:10001:' >> /etc/group \
    && echo 'exactdocs:x:10001:10001::/data:/usr/sbin/nologin' >> /etc/passwd

# --- the application on top of the tools, without its virtualenv. CI builds `runtime-tools`
# alone for linux/amd64 (QEMU).
FROM runtime-tools AS app
COPY --from=builder --chown=10001:10001 /data /data
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
# Readiness: unhealthy while the database does not answer (README *Health checks*). The client
# waits 3 s, longer than readiness waits for the database (2 s), so a 503 and its reason arrive.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/readyz', timeout=3)"]
ENTRYPOINT ["tini", "--", "exactdocs"]
CMD ["serve"]

# The variants. Metadata last in each: it changes on every build and must not invalidate the
# layers above. `base` is the last stage, so a build without --target gives it.
FROM app AS ai
COPY --from=build-ai /app/.venv /app/.venv
ARG VERSION=0.0.0
ARG REVISION=unknown
ARG CREATED=unknown
LABEL org.opencontainers.image.title="ExactDocs (AI)" \
      org.opencontainers.image.description="Self-hosted, version-accurate documentation for AI coding agents, with AI retrieval (exactdocs[ai])" \
      org.opencontainers.image.source="https://github.com/SirCypkowskyy/ExactDocs" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}"

# Root-owned and read-only for UID 10001: the models are part of the image, never changed at run
# time; `exactdocs models pull` into another EXACTDOCS_MODELS_DIR (a volume) adds others.
FROM app AS local
COPY --from=build-local /app/.venv /app/.venv
COPY --from=models /opt/exactdocs/models /opt/exactdocs/models
ENV EXACTDOCS_MODELS_DIR=/opt/exactdocs/models
ARG VERSION=0.0.0
ARG REVISION=unknown
ARG CREATED=unknown
LABEL org.opencontainers.image.title="ExactDocs (local models)" \
      org.opencontainers.image.description="Self-hosted, version-accurate documentation for AI coding agents, with local embedding and reranking models (exactdocs[ai,local])" \
      org.opencontainers.image.source="https://github.com/SirCypkowskyy/ExactDocs" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}"

FROM app AS base
COPY --from=build /app/.venv /app/.venv
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
