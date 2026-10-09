#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

echo "deploy_test.sh 已停用：测试环境已迁移为预发环境，正在转交 deploy_pre.sh。" >&2
exec "$SCRIPT_DIR/deploy_pre.sh" "$@"
