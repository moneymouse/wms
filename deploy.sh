#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

usage() {
	echo "Usage: ./deploy.sh [--migrate]"
	echo "  --migrate    部署时执行数据库迁移（默认不迁移）"
}

RUN_MIGRATIONS="false"

for arg in "$@"; do
	case "$arg" in
		--migrate)
			RUN_MIGRATIONS="true"
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "Unknown argument: $arg"
			usage
			exit 1
			;;
	esac
done

echo "Deploy start (RUN_MIGRATIONS=$RUN_MIGRATIONS)"

# Check the shared certificate before building or replacing any deployed files.
ssh Ali 'bash -s' <<'REMOTE_PREFLIGHT'
set -euo pipefail
cd ~/wms/wms_backend
for file in DB.env BK.env env.toml; do
    [[ -f "$file" ]] || { echo "Missing production configuration: $file" >&2; exit 1; }
done
certificate_dir="${PROD_TLS_DIR:-../../wms_pre_tls}/letsencrypt/live/wms-pre-ip"
[[ -f "$certificate_dir/fullchain.pem" && -f "$certificate_dir/privkey.pem" ]] || {
    echo "Missing production TLS certificate; expected the shared wms-pre-ip certificate." >&2
    exit 1
}
openssl x509 -in "$certificate_dir/fullchain.pem" -noout -checkend 0
REMOTE_PREFLIGHT

cd wms_frontend/
npm run build
cd "$SCRIPT_DIR"

rsync -avz --delete \
	--exclude='wms_frontend/src/' \
	--exclude='*.env' \
	--exclude='*/env.toml' \
	--exclude='backups/' \
	--exclude='*/.git/' \
	--exclude='*/.pytest_cache/' \
	--exclude='*/__pycache__/' \
	--exclude='wms_frontend/node_modules/' \
	--exclude='.well-known/acme-challenge/' \
	--exclude='wms_backend/log/' \
	--exclude='wms_backend/excels/' \
	--exclude='wms_backend/data/history/' \
	--exclude='wms_backend/static/' \
	--exclude='wms_backend/uploads/' \
	. Ali:~/wms

ssh Ali "cd ~/wms/wms_backend && RUN_MIGRATIONS=$RUN_MIGRATIONS bash -s" <<'REMOTE_DEPLOY'
set -euo pipefail
bash scripts/init_prod_mcp_env.sh
compose=(docker compose -f docker-compose.yml --profile mcp)
"${compose[@]}" config --quiet
# This SSH script arrives on stdin; the one-off check must not consume it.
"${compose[@]}" run --rm --no-deps --interactive=false -T --entrypoint nginx nginx -t < /dev/null
"${compose[@]}" up -d --build mysql backend mcp
# rsync replaces the configuration inode; recreate the proxy to refresh its bind.
"${compose[@]}" up -d --no-deps --force-recreate nginx

echo "Production HTTPS and MCP configured; the existing TLS renewal job is retained."
REMOTE_DEPLOY

echo "Deploy done"
