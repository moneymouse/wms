#!/usr/bin/env bash
# Run on Ali using an isolated Certbot venv or Docker; manage Nginx via Docker CLI.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${PRE_BACKEND_DIR:-$(dirname -- "$SCRIPT_DIR")}"
PRE_TLS_DIR="${PRE_TLS_DIR:-$(dirname -- "$BACKEND_DIR")/../wms_pre_tls}"
PRE_TLS_WEBROOT="${PRE_TLS_WEBROOT:-$HOME/wms/wms_frontend/build}"
PRE_TLS_CERT_NAME="${PRE_TLS_CERT_NAME:-wms-pre-ip}"
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot:v5.8.0}"
export PRE_TLS_DIR

renew_args=()
case "${1:-}" in
    "") ;;
    --dry-run) renew_args=(--dry-run --run-deploy-hooks) ;;
    *) echo "Usage: $0 [--dry-run]" >&2; exit 1 ;;
esac
[[ $# -le 1 ]] || { echo "Usage: $0 [--dry-run]" >&2; exit 1; }

command -v docker >/dev/null
command -v flock >/dev/null
[[ -d "$PRE_TLS_DIR/letsencrypt" && -d "$PRE_TLS_WEBROOT" ]] || {
    echo "Missing certificate directory or HTTP-01 webroot." >&2
    exit 1
}
mkdir -p "$PRE_TLS_DIR/work" "$PRE_TLS_DIR/logs"
exec 9>"$PRE_TLS_DIR/renew.lock"
flock -n 9 || exit 0

compose=(docker compose --project-directory "$BACKEND_DIR"
    -f "$BACKEND_DIR/docker-compose.pre.yml"
    -f "$BACKEND_DIR/docker-compose.pre.tls.yml" --profile mcp)
reload_marker="$PRE_TLS_DIR/work/nginx-reload-needed"

certbot_bin="${CERTBOT_BIN:-}"
if [[ -z "$certbot_bin" && -x "$PRE_TLS_DIR/certbot-venv/bin/certbot" ]]; then
    certbot_bin="$PRE_TLS_DIR/certbot-venv/bin/certbot"
fi
if [[ -n "$certbot_bin" ]]; then
    [[ -x "$certbot_bin" ]] || { echo "CERTBOT_BIN is not executable." >&2; exit 1; }
    # Certbot runs hooks with /bin/sh, so use POSIX single-quote escaping.
    quoted_marker="$(printf '%s' "$reload_marker" | sed "s/'/'\\\\''/g")"
    "$certbot_bin" renew --cert-name "$PRE_TLS_CERT_NAME" \
        --config-dir "$PRE_TLS_DIR/letsencrypt" \
        --work-dir "$PRE_TLS_DIR/work" --logs-dir "$PRE_TLS_DIR/logs" \
        --webroot --webroot-path "$PRE_TLS_WEBROOT" \
        --non-interactive --quiet --no-random-sleep-on-renew \
        --deploy-hook "touch -- '$quoted_marker'" "${renew_args[@]}"
else
    docker run --rm \
        --user "$(id -u):$(id -g)" \
        --volume "$PRE_TLS_DIR/letsencrypt:/etc/letsencrypt" \
        --volume "$PRE_TLS_DIR/work:/var/lib/letsencrypt" \
        --volume "$PRE_TLS_DIR/logs:/var/log/letsencrypt" \
        --volume "$PRE_TLS_WEBROOT:/var/www/acme" \
        "$CERTBOT_IMAGE" renew --cert-name "$PRE_TLS_CERT_NAME" \
        --webroot --webroot-path /var/www/acme --non-interactive --quiet \
        --no-random-sleep-on-renew \
        --deploy-hook 'touch /var/lib/letsencrypt/nginx-reload-needed' \
        "${renew_args[@]}"
fi

# A hook runs only after successful renewal. Keep the marker if syntax validation
# or reload fails, so the next scheduled run retries the reload.
if [[ -f "$reload_marker" ]]; then
    "${compose[@]}" exec -T nginx nginx -t
    "${compose[@]}" exec -T nginx nginx -s reload

    # The existing renewal job also refreshes production once it uses this
    # certificate. Leave HTTP-only production unchanged before its TLS rollout.
    certificate_source="$(cd -- "$PRE_TLS_DIR/letsencrypt" && pwd -P)"
    production_container="$(docker ps -a --filter 'name=^/wms_nginx$' --format '{{.Names}}')"
    if [[ -n "$production_container" ]]; then
        production_certificate_source="$(docker inspect --format \
            '{{range .Mounts}}{{if eq .Destination "/etc/letsencrypt"}}{{.Source}}{{end}}{{end}}' \
            wms_nginx)"
        if [[ "$production_certificate_source" -ef "$certificate_source" ]]; then
            docker exec wms_nginx nginx -t
            docker exec wms_nginx nginx -s reload
        fi
    fi
    rm -- "$reload_marker"
    echo "$(date -Iseconds): TLS renewal hook completed; Nginx reloaded."
fi
