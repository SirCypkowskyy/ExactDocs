#!/usr/bin/env bash
# Persistent CI runners usually already have Chromium's system libraries.
set -euo pipefail
cd "$(dirname "$0")"

fail() { echo "::error::$*" >&2; exit 1; }
probe() { timeout --kill-after=5s 30s node probe-chromium.cjs; }

# A missing/corrupt browser cache must not turn into an unbounded download either.
timeout --kill-after=10s 180s pnpm exec playwright install chromium \
  || fail "Chromium download failed or exceeded 180 seconds"
if probe; then
  echo "Chromium already works; skipping system dependency installation"
  exit 0
fi

# Resolve the public CLI as this user; invoke Node directly under sudo so no package
# manager or user-controlled PATH needs to be carried into the privileged process.
node_bin=$(command -v node)
playwright_cli=$(node -p "require.resolve('@playwright/test/cli')")
apt_config=$(mktemp)
trap 'rm -f "$apt_config"' EXIT
cat > "$apt_config" <<'APT'
Acquire::http::Timeout "15";
Acquire::https::Timeout "15";
Acquire::Retries "1";
APT
# APT_CONFIG applies only to this process tree. Put timeout INSIDE sudo so it can
# terminate the privileged installer and its descendants, including stalled APT.
sudo -n env APT_CONFIG="$apt_config" timeout --kill-after=10s 180s \
  "$node_bin" "$playwright_cli" install-deps chromium \
  || fail "Chromium system dependency installation failed or exceeded 180 seconds (passwordless sudo required)"
probe || fail "Chromium still cannot launch and render after system dependency installation"
