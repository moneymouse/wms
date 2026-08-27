#!/bin/bash

set -euo pipefail

BACKEND_DIR="${1:-$(pwd)}"
DB_ENV="$BACKEND_DIR/PRE_DB.env"
BK_ENV="$BACKEND_DIR/PRE_BK.env"

if [[ -e "$DB_ENV" || -e "$BK_ENV" ]]; then
    if [[ -f "$DB_ENV" && -f "$BK_ENV" ]]; then
        echo "Pre-production environment files already exist; leaving them unchanged."
        exit 0
    fi

    echo "Refusing to continue: PRE_DB.env and PRE_BK.env must either both exist or both be absent." >&2
    exit 1
fi

command -v openssl >/dev/null 2>&1 || {
    echo "openssl is required to generate pre-production credentials." >&2
    exit 1
}

MYSQL_ROOT_PASSWORD="$(openssl rand -hex 32)"
MYSQL_PASSWORD="$(openssl rand -hex 32)"

umask 077

printf '%s\n' \
    "MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PASSWORD" \
    "MYSQL_DATABASE=wms_pre" \
    "MYSQL_USER=wms_pre_app" \
    "MYSQL_PASSWORD=$MYSQL_PASSWORD" \
    > "$DB_ENV"

printf '%s\n' \
    "DATABASE_URL=mysql+pymysql://wms_pre_app:$MYSQL_PASSWORD@mysql:3306/wms_pre?charset=utf8mb4" \
    "FLASK_ENV=production" \
    > "$BK_ENV"

chmod 600 "$DB_ENV" "$BK_ENV"
echo "Created PRE_DB.env and PRE_BK.env with mode 600."
