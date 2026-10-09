#!/usr/bin/env bash
# Add production MCP settings without sourcing or replacing existing credentials.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${1:-$(dirname -- "$SCRIPT_DIR")}"
BK_ENV="$BACKEND_DIR/BK.env"
[[ $# -le 1 ]] || { echo "Usage: $0 [backend-directory]" >&2; exit 1; }
[[ -f "$BK_ENV" ]] || {
    echo "Missing production BK.env; configure the production database first." >&2
    exit 1
}

# Read dotenv values as data. Never source BK.env or print its credentials.
read_env_value() {
    awk -v target="$1" '
    function key(line) {
        sub(/^[ \t]*(export[ \t]+)?/, "", line)
        if (line !~ /^[A-Za-z_][A-Za-z0-9_]*[ \t]*=/) return ""
        sub(/[ \t]*=.*/, "", line)
        return line
    }
    function value(line, first, i) {
        sub(/^[^=]*=/, "", line)
        sub(/\r$/, "", line)
        sub(/^[ \t]+/, "", line)
        sub(/[ \t]+$/, "", line)
        first = substr(line, 1, 1)
        if (first == "\047" || first == "\042") {
            for (i = 2; i <= length(line); i++)
                if (substr(line, i, 1) == first && substr(line, i - 1, 1) != "\\")
                    return substr(line, 2, i - 2)
        } else {
            sub(/[ \t]+#.*$/, "", line)
            sub(/^#.*$/, "", line)
            sub(/[ \t]+$/, "", line)
        }
        return line
    }
    key($0) == target { result = value($0) }
    END { printf "%s", result }
    ' "$BK_ENV"
}

csv_contains() {
    printf '%s\n' "$1" | awk -v expected="$2" '
        BEGIN { FS = "," }
        {
            for (i = 1; i <= NF; i++) {
                item = $i
                sub(/^[ \t]+/, "", item)
                sub(/[ \t]+$/, "", item)
                if (item == expected) found = 1
            }
        }
        END { exit !found }
    '
}

issuer="$(read_env_value OAUTH_ISSUER_URL)"
resource="$(read_env_value MCP_PUBLIC_URL)"
allow_http="$(read_env_value OAUTH_ALLOW_LOCAL_HTTP)"
allowed_hosts="$(read_env_value MCP_ALLOWED_HOSTS)"
allowed_origins="$(read_env_value MCP_ALLOWED_ORIGINS)"
if [[ -n "$issuer" && "$issuer" != "https://8.166.137.88" ]]; then
    echo "OAUTH_ISSUER_URL does not match the production TLS address; correct BK.env before deployment." >&2
    exit 1
fi
if [[ -n "$resource" && "$resource" != "https://8.166.137.88/mcp" ]]; then
    echo "MCP_PUBLIC_URL does not match the production TLS address; correct BK.env before deployment." >&2
    exit 1
fi
case "$allow_http" in
    ""|false|False|FALSE|0|no|No|NO) ;;
    *)
        echo "OAUTH_ALLOW_LOCAL_HTTP must be false for production TLS; correct BK.env before deployment." >&2
        exit 1
        ;;
esac
if [[ -n "$allowed_hosts" ]] && ! csv_contains "$allowed_hosts" "8.166.137.88"; then
    echo "MCP_ALLOWED_HOSTS must include the production host; correct BK.env before deployment." >&2
    exit 1
fi
if [[ -n "$allowed_origins" ]] && ! csv_contains "$allowed_origins" "https://8.166.137.88"; then
    echo "MCP_ALLOWED_ORIGINS must include the production TLS origin; correct BK.env before deployment." >&2
    exit 1
fi
existing_secret="$(read_env_value OAUTH_SESSION_SECRET)"

if [[ -n "$existing_secret" && ${#existing_secret} -lt 32 ]]; then
    echo "Existing OAUTH_SESSION_SECRET is shorter than 32 characters; update it before deployment." >&2
    exit 1
fi

new_secret=""
if [[ -z "$existing_secret" ]]; then
    command -v openssl >/dev/null 2>&1 || {
        echo "openssl is required to generate the production OAuth secret." >&2
        exit 1
    }
    new_secret="$(openssl rand -hex 32)"
fi

umask 077
defaults_file="$(mktemp "$BACKEND_DIR/.mcp-defaults.XXXXXX")"
output_file=""
trap 'rm -f -- "$defaults_file" "${output_file:-}"' EXIT
output_file="$(mktemp "$BACKEND_DIR/.BK.env.XXXXXX")"

printf '%s\n' \
    'OAUTH_ISSUER_URL=https://8.166.137.88' \
    'MCP_PUBLIC_URL=https://8.166.137.88/mcp' \
    'MCP_ALLOWED_HOSTS=8.166.137.88' \
    'MCP_ALLOWED_ORIGINS=https://8.166.137.88' \
    'OAUTH_ALLOW_LOCAL_HTTP=false' \
    "OAUTH_SESSION_SECRET=$new_secret" > "$defaults_file"

# Resolve the last assignment of each key, as Compose does. Preserve all existing
# nonempty settings and all unrelated lines; replace only missing/empty settings.
awk '
    function key(line) {
        sub(/^[ \t]*(export[ \t]+)?/, "", line)
        if (line !~ /^[A-Za-z_][A-Za-z0-9_]*[ \t]*=/) return ""
        sub(/[ \t]*=.*/, "", line)
        return line
    }
    function value(line, first, i) {
        sub(/^[^=]*=/, "", line)
        sub(/\r$/, "", line)
        sub(/^[ \t]+/, "", line)
        sub(/[ \t]+$/, "", line)
        first = substr(line, 1, 1)
        if (first == "\047" || first == "\042") {
            for (i = 2; i <= length(line); i++)
                if (substr(line, i, 1) == first && substr(line, i - 1, 1) != "\\")
                    return substr(line, 2, i - 2)
        } else {
            sub(/[ \t]+#.*$/, "", line)
            sub(/^#.*$/, "", line)
            sub(/[ \t]+$/, "", line)
        }
        return line
    }
    FNR == NR {
        name = key($0)
        defaults[name] = $0
        order[++count] = name
        next
    }
    {
        lines[++line_count] = $0
        name = key($0)
        if (name in defaults) {
            names[line_count] = name
            last_line[name] = line_count
            effective[name] = value($0)
        }
    }
    END {
        for (i = 1; i <= line_count; i++) {
            name = names[i]
            if (name != "" && effective[name] == "") {
                if (last_line[name] == i) print defaults[name]
            } else print lines[i]
        }
        for (i = 1; i <= count; i++) {
            name = order[i]
            if (!(name in last_line)) print defaults[name]
        }
    }
' "$defaults_file" "$BK_ENV" > "$output_file"

chmod 600 "$BK_ENV" "$output_file"
if cmp -s "$BK_ENV" "$output_file"; then
    echo "Production MCP settings already configured; BK.env kept with mode 600."
else
    mv -- "$output_file" "$BK_ENV"
    echo "Added missing production MCP settings to BK.env with mode 600."
fi
