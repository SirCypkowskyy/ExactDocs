#!/usr/bin/env bash
# Cloudflare helpers for the trial instance: one tunnel ingress rule and one DNS record.
# Source it, don't run it. Same rules as TuttiTrip's deploy/cloudflare.sh
# (HackYeah-TuttiTripTeam/tuttitrip-backend), whose tunnel this shares.
# Needs: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_TUNNEL_ID and (for DNS)
# CLOUDFLARE_ZONE_ID; ED_STATE_DIR and ed_log from deploy.sh.
#
# The tunnel is shared with other services. We only ever add or remove the one hostname below,
# insert it before any wildcard, and back up the full config before every write. A remotely
# managed tunnel picks up config changes live: cloudflared is never restarted.

CF_API="https://api.cloudflare.com/client/v4"
CF_MARK="managed-by=exactdocs-trial-deploy"
# The only hostname this tooling may touch.
CF_HOST_RE='^exact-docs\.gburek\.app$'

cf_api() {
  local method=$1 url=$2 body=${3:-}
  local args=(-sS --max-time 30 -X "$method" -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN:?}" \
    -H "Content-Type: application/json" "$CF_API$url")
  if [ -n "$body" ]; then args+=(--data "$body"); fi
  curl "${args[@]}"
}

cf_config_url() {
  printf '/accounts/%s/cfd_tunnel/%s/configurations' "${CLOUDFLARE_ACCOUNT_ID:?}" "${CLOUDFLARE_TUNNEL_ID:?}"
}

cf_check_host() {
  [[ $1 =~ $CF_HOST_RE ]] || { ed_log "refusing foreign hostname $1"; return 1; }
}

# Print the tunnel config JSON (.result.config). Refuse a config that does not look like the
# shared tunnel's: an ingress list whose last rule is the hostname-less catch-all.
cf_get_config() {
  local resp config
  resp=$(cf_api GET "$(cf_config_url)")
  if [ "$(jq -r '.success' <<<"$resp")" != true ]; then
    ed_log "cannot read tunnel config: $(jq -c '.errors' <<<"$resp")"; return 1
  fi
  config=$(jq '.result.config' <<<"$resp")
  if ! jq -e '(.ingress | type == "array") and (.ingress | length > 0)
              and (.ingress[-1].hostname // null) == null' <<<"$config" >/dev/null; then
    ed_log "tunnel config has no ingress list ending in a catch-all rule; not touching it"; return 1
  fi
  printf '%s\n' "$config"
}

# cf_put_config <old-json> <new-json>: back up old, write new if different.
cf_put_config() {
  local old=$1 new=$2 backup resp
  if [ "$(jq -S . <<<"$old")" = "$(jq -S . <<<"$new")" ]; then ed_log "tunnel ingress unchanged"; return 0; fi
  mkdir -p "$ED_STATE_DIR/backups"
  backup="$ED_STATE_DIR/backups/tunnel-config-$(date -u +%Y%m%dT%H%M%SZ)-$$.json"
  printf '%s\n' "$old" >"$backup"
  # shellcheck disable=SC2012  # our own timestamped file names
  ls -1t "$ED_STATE_DIR"/backups/tunnel-config-*.json | tail -n +51 | xargs -r rm -f  # keep 50
  resp=$(cf_api PUT "$(cf_config_url)" "$(jq -c '{config: .}' <<<"$new")")
  if [ "$(jq -r '.success' <<<"$resp")" != true ]; then
    ed_log "tunnel config update failed: $(jq -c '.errors' <<<"$resp") (backup: $backup)"; return 1
  fi
  ed_log "tunnel ingress updated (previous config: $backup)"
}

# cf_ingress_ensure <hostname> <service>: our rule goes first, before any wildcard.
cf_ingress_ensure() {
  local host=$1 service=$2 old new
  cf_check_host "$host" || return 1
  old=$(cf_get_config) || return 1
  new=$(jq --arg h "$host" --arg s "$service" '
    .ingress = ([{hostname: $h, service: $s}] + [.ingress[] | select(.hostname != $h)])' <<<"$old")
  cf_put_config "$old" "$new"
}

# cf_ingress_remove <hostname>: drop only our hostname.
cf_ingress_remove() {
  local host=$1 old new
  cf_check_host "$host" || return 1
  old=$(cf_get_config) || return 1
  new=$(jq --arg h "$host" '.ingress = [.ingress[] | select((.hostname // "") != $h)]' <<<"$old")
  cf_put_config "$old" "$new"
}

# DNS is best effort: a proxied wildcard *.gburek.app may already cover the host, and the token
# may lack Zone:DNS:Edit. Failures are logged, never fatal.
cf_dns_ensure() {
  local host=$1 resp
  cf_check_host "$host" || return 1
  [ -n "${CLOUDFLARE_ZONE_ID:-}" ] || { ed_log "CLOUDFLARE_ZONE_ID unset, skipping DNS"; return 0; }
  resp=$(cf_api GET "/zones/$CLOUDFLARE_ZONE_ID/dns_records?name=$host") || resp='{}'
  if [ "$(jq -r '.success' <<<"$resp" 2>/dev/null)" != true ]; then
    ed_log "DNS not managed (token lacks DNS access?): $(jq -c '.errors' <<<"$resp" 2>/dev/null); relying on wildcard"
    return 0
  fi
  if [ "$(jq '.result | length' <<<"$resp")" != 0 ]; then ed_log "DNS record for $host exists"; return 0; fi
  resp=$(cf_api POST "/zones/$CLOUDFLARE_ZONE_ID/dns_records" "$(jq -nc --arg n "$host" \
    --arg c "$CLOUDFLARE_TUNNEL_ID.cfargotunnel.com" --arg m "$CF_MARK" \
    '{type: "CNAME", name: $n, content: $c, proxied: true, comment: $m}')") || resp='{}'
  ed_log "DNS create $host: success=$(jq -r '.success' <<<"$resp" 2>/dev/null) $(jq -c '.errors' <<<"$resp" 2>/dev/null)"
}

# Remove only the record we created (marked in its comment).
cf_dns_remove() {
  local host=$1 resp id
  cf_check_host "$host" || return 1
  [ -n "${CLOUDFLARE_ZONE_ID:-}" ] || return 0
  resp=$(cf_api GET "/zones/$CLOUDFLARE_ZONE_ID/dns_records?name=$host") || return 0
  [ "$(jq -r '.success' <<<"$resp")" = true ] || return 0
  jq -r --arg m "$CF_MARK" '.result[] | select(.comment == $m) | .id' <<<"$resp" | while read -r id; do
    cf_api DELETE "/zones/$CLOUDFLARE_ZONE_ID/dns_records/$id" >/dev/null && ed_log "DNS record $host removed"
  done
}
