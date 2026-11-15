#!/usr/bin/env bash
# Build and (re)deploy the trial instance https://exact-docs.gburek.app from this checkout.
#   deploy/trial/deploy.sh [git-sha]
# Runs on dellpromaxgb10 itself, from the host runner labelled `exactdocs-deploy`
# (.github/workflows/trial-deploy.yml; docs/deployment.md, "Trial instance"). Modelled on TuttiTrip's
# deploy/deploy.sh, whose shared Cloudflare tunnel it uses.
# Env: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_TUNNEL_ID, CLOUDFLARE_ZONE_ID (optional),
#      EXACTDOCS_TRIAL_PORT (optional, default 18090).
# Host files (never committed), under $ED_STATE_DIR (~/exactdocs-trial), all mode 600:
#      trial.env       EXACTDOCS_SECRET_KEY, generated on the first run and never overwritten
#      admin-password  the password of the first admin `admin`, generated once, never printed
#      deploy.lock     held while anything on the host changes
#      backups/        the tunnel config before each write (the last 50)
# Everything it creates is named exactdocs-trial* and labelled exactdocs.managed=true; it never
# touches another container, image, volume or hostname.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)

ED_STATE_DIR="${ED_STATE_DIR:-$HOME/exactdocs-trial}"
ed_log() { printf '[exactdocs-trial] %s\n' "$*" >&2; }
# shellcheck source=deploy/trial/cloudflare.sh
. "$here/cloudflare.sh"

[ "$(hostname)" = dellpromaxgb10 ] \
  || { ed_log "trial deploy runs only on dellpromaxgb10"; exit 1; }

sha=${1:-$(git -C "$repo" rev-parse HEAD)}
[[ $sha =~ ^[0-9a-f]{12,40}$ ]] || { ed_log "not a commit sha: $sha"; exit 1; }
host="exact-docs.gburek.app"
container="exactdocs-trial"
volume="exactdocs-trial-data"
image="exactdocs-trial:${sha:0:12}"
port="${EXACTDOCS_TRIAL_PORT:-18090}"
# Published on the docker0 bridge address only: the cloudflared container (default bridge)
# reaches it, the LAN does not.
bind="172.17.0.1:$port"
labels=(--label exactdocs.managed=true --label exactdocs.role=trial --label "exactdocs.sha=$sha")

umask 077
mkdir -p "$ED_STATE_DIR"
chmod 700 "$ED_STATE_DIR"
exec 9>"$ED_STATE_DIR/deploy.lock"
flock 9  # one deploy at a time on this host

# A surviving data volume needs the original encryption key and admin password. Generating
# replacements would invalidate stored credentials and advertise a password that cannot sign in.
if docker volume inspect "$volume" >/dev/null 2>&1; then
  if [ ! -s "$ED_STATE_DIR/trial.env" ] || [ ! -s "$ED_STATE_DIR/admin-password" ]; then
    ed_log "existing data volume: restore trial.env and admin-password from backup before deploying"
    exit 1
  fi
fi

# Resource names alone do not authorize replacing someone else's container or data volume.
require_managed() {
  local kind=$1 name=$2 template=$3
  if docker "$kind" inspect "$name" >/dev/null 2>&1; then
    if [ "$(docker "$kind" inspect --format "$template" "$name")" != true ]; then
      ed_log "refusing unmanaged $kind $name"
      exit 1
    fi
  fi
}
require_managed container "$container" '{{ index .Config.Labels "exactdocs.managed" }}'
require_managed volume "$volume" '{{ index .Labels "exactdocs.managed" }}'

# --- secrets, created once ------------------------------------------------------------------
gen_secret() { head -c "$1" /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$2"; }
envfile="$ED_STATE_DIR/trial.env"
if [ ! -e "$envfile" ]; then
  printf 'EXACTDOCS_SECRET_KEY=%s\n' "$(gen_secret 96 64)" >"$envfile"
  ed_log "generated EXACTDOCS_SECRET_KEY in $envfile"
fi
grep -q '^EXACTDOCS_SECRET_KEY=.\{32,\}' "$envfile" \
  || { ed_log "$envfile has no EXACTDOCS_SECRET_KEY of 32+ characters; fix it by hand"; exit 1; }
pwfile="$ED_STATE_DIR/admin-password"
if [ ! -e "$pwfile" ]; then
  gen_secret 64 32 >"$pwfile"
  ed_log "generated the admin password in $pwfile"
fi
chmod 600 "$envfile" "$pwfile"

# --- the port is ours or free -----------------------------------------------------------------
users=$(docker ps -a --filter "publish=$port" --format '{{.Names}}' | grep -vx "$container" || true)
if [ -n "$users" ]; then ed_log "port $port is published by another container: $users"; exit 1; fi
if ! docker container inspect "$container" >/dev/null 2>&1 \
  && [ -n "$(ss -Htln "sport = :$port" 2>/dev/null)" ]; then
  ed_log "port $port is in use on this host; set EXACTDOCS_TRIAL_PORT to a free one"; exit 1
fi

# --- build from the checkout (no registry login; develop is what runs) ---------------------
ed_log "building $image (target local) from $sha"
DOCKER_BUILDKIT=1 docker build -q -f "$repo/deploy/Dockerfile" --target local -t "$image" \
  --build-arg "VERSION=0.0.0+trial.${sha:0:12}" --build-arg "REVISION=$sha" \
  --build-arg "CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${labels[@]}" "$repo" >/dev/null
ed_log "built $image"

hardened=(--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true
  -v "$volume:/data" --env-file "$envfile")
docker volume inspect "$volume" >/dev/null 2>&1 \
  || docker volume create --label exactdocs.managed=true "$volume" >/dev/null

# --- the first admin, before the server (and long before the route) exists -----------------
# `admin create` opens the database directly and refuses once any account exists.
set +e
out=$(docker run --rm -i "${hardened[@]}" "$image" admin create --username admin --password-stdin \
  <"$pwfile" 2>&1)
rc=$?
set -e
if [ "$rc" = 0 ]; then
  ed_log "created the first admin 'admin' (password in $pwfile)"
elif grep -q 'already set up' <<<"$out"; then
  ed_log "an admin exists already"
else
  ed_log "admin create failed (exit $rc):"; printf '%s\n' "$out" | tail -n 20 >&2; exit 1
fi

# --- swap the container -----------------------------------------------------------------------
docker rm -f "$container" >/dev/null 2>&1 || true
docker run -d --name "$container" --restart unless-stopped "${labels[@]}" "${hardened[@]}" \
  --cpus 2 --memory 4g \
  -e EXACTDOCS_ALLOWED_HOSTS="$host" -e EXACTDOCS_PUBLIC_URL="https://$host" \
  -e EXACTDOCS_FORWARDED_ALLOW_IPS=172.17.0.1 \
  -p "$bind:3000" "$image" >/dev/null
ed_log "started $container on $bind"

for i in $(seq 90); do
  if curl -fsS --max-time 5 "http://$bind/readyz" >/dev/null 2>&1; then break; fi
  [ "$i" = 90 ] && { ed_log "readiness check failed"; docker logs --tail 50 "$container" >&2; exit 1; }
  sleep 2
done
ed_log "ready on $bind"

# The instance must not offer the first-admin setup to whoever comes first.
state=$(curl -fsS --max-time 5 -H "Host: $host" "http://$bind/api/v1/session" | jq -r '.state // empty' || true)
if [ "$state" != signed_out ]; then
  ed_log "the instance answers session state '${state:-unknown}'; no admin, not routing it"
  docker rm -f "$container" >/dev/null 2>&1 || true
  if cf_ingress_remove "$host"; then ed_log "removed any route to $host"; fi
  exit 1
fi
ed_log "session state '$state': the setup is done"

# --- routing ------------------------------------------------------------------------------------
cf_ingress_ensure "$host" "http://$bind"
cf_dns_ensure "$host"

# Old images of the trial (keep the one just deployed).
docker image ls exactdocs-trial --filter label=exactdocs.managed=true --format '{{.Repository}}:{{.Tag}}' \
  | grep -vx "$image" | xargs -r docker rmi >/dev/null 2>&1 || true
ed_log "deployed $sha -> https://$host"
