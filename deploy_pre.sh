#!/bin/bash

set -euo pipefail

usage() {
	echo "Usage: ./deploy_pre.sh [--migrate] [--skip-build] [--host <ssh_host>] [--remote-dir <path>]"
	echo "  --migrate             部署时执行数据库迁移（默认不迁移）"
	echo "  --skip-build          跳过前端构建"
	echo "  --host <ssh_host>     远程 SSH 主机，默认 Ali"
	echo "  --remote-dir <path>   远程预发目录，默认 ~/wms_pre"
}

RUN_MIGRATIONS="false"
SKIP_BUILD="false"
REMOTE_HOST="Ali"
REMOTE_DIR="~/wms_pre"

while [[ $# -gt 0 ]]; do
	case "$1" in
		--migrate)
			RUN_MIGRATIONS="true"
			shift
			;;
		--skip-build)
			SKIP_BUILD="true"
			shift
			;;
		--host)
			REMOTE_HOST="${2:-}"
			[[ -n "$REMOTE_HOST" ]] || { echo "--host 需要提供值"; exit 1; }
			shift 2
			;;
		--remote-dir)
			REMOTE_DIR="${2:-}"
			[[ -n "$REMOTE_DIR" ]] || { echo "--remote-dir 需要提供值"; exit 1; }
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "Unknown argument: $1"
			usage
			exit 1
			;;
	esac
done

case "$REMOTE_DIR" in
	"~/wms"|"/home/tony/wms")
		echo "拒绝部署：预发脚本不能指向生产目录 $REMOTE_DIR" >&2
		exit 1
		;;
esac

echo "Pre-production deploy start (RUN_MIGRATIONS=$RUN_MIGRATIONS, SKIP_BUILD=$SKIP_BUILD)"
echo "Remote: $REMOTE_HOST:$REMOTE_DIR"

if [[ "$SKIP_BUILD" != "true" ]]; then
	cd wms_frontend/
	npm run build
	cd - >/dev/null
fi

# Runner ownership does not apply to the server's deploy user or shared group.
rsync -avz --no-owner --no-group --delete \
	--exclude='wms_frontend/src/' \
	--exclude='*.env' \
	--exclude='*/env.toml' \
	--exclude='backups/' \
	--exclude='.git/' \
	--exclude='*/.pytest_cache/' \
	--exclude='*/__pycache__/' \
	--exclude='wms_frontend/node_modules/' \
	--exclude='wms_backend/log/' \
	--exclude='wms_backend/log_pre/' \
	--exclude='wms_backend/excels/' \
	--exclude='wms_backend/excels_pre/' \
	--exclude='wms_backend/uploads/' \
	--exclude='wms_backend/uploads_pre/' \
	--exclude='wms_backend/data/history/' \
	--exclude='wms_backend/data/history_pre/' \
	. "$REMOTE_HOST:$REMOTE_DIR"

ssh "$REMOTE_HOST" "cd $REMOTE_DIR/wms_backend && RUN_MIGRATIONS=$RUN_MIGRATIONS bash -s" <<'REMOTE_DEPLOY'
set -euo pipefail
test -f PRE_DB.env
test -f PRE_BK.env
compose=(docker compose -f docker-compose.pre.yml)
export PRE_TLS_DIR="${PRE_TLS_DIR:-../../wms_pre_tls}"
certificate_dir="$PRE_TLS_DIR/letsencrypt/live/wms-pre-ip"
if [[ -d "$certificate_dir" ]]; then
    [[ -f "$certificate_dir/fullchain.pem" && -f "$certificate_dir/privkey.pem" ]] || {
        echo "TLS certificate is incomplete; leaving running services unchanged." >&2
        exit 1
    }
    compose+=(-f docker-compose.pre.tls.yml --profile mcp)
    echo "Pre-production TLS certificate found; enabling HTTPS and MCP."
    # Check SSL files and Nginx syntax before replacing the live proxy.
    # This SSH script arrives on stdin; the one-off check must not consume it.
    "${compose[@]}" run --rm --no-deps --interactive=false -T --entrypoint nginx nginx -t < /dev/null
    "${compose[@]}" up -d --build mysql backend mcp
    # rsync replaces a config inode; recreate only the proxy to refresh its bind.
    "${compose[@]}" up -d --no-deps --force-recreate nginx
else
    "${compose[@]}" up -d --build
fi
REMOTE_DEPLOY

echo "Pre-production deploy done"
