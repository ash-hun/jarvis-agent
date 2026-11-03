#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PROFILE="web"

cd "$PROJECT_DIR"

# --web 플래그: 예전 호출을 깨지 않으려고 받기만 한다. 프로파일은 web 하나뿐이다
if [[ "${1:-}" == "--web" ]]; then
  shift
fi

echo "[restart] Stopping profile=$PROFILE..."
docker compose --profile "$PROFILE" down 2>/dev/null || true

if [[ "${1:-}" == "--build" ]]; then
  echo "[restart] Rebuilding images..."
  docker compose --profile "$PROFILE" build
  shift
fi

echo "[restart] Starting profile=$PROFILE..."
# backend + frontend 동시 기동, 로그 스트리밍
exec docker compose --profile "$PROFILE" up --remove-orphans
