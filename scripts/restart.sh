#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PROFILE="app"

cd "$PROJECT_DIR"

# --web 플래그: Web HUD 모드 (backend + frontend 동시 실행)
if [[ "${1:-}" == "--web" ]]; then
  PROFILE="web"
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
if [[ "$PROFILE" == "web" ]]; then
  # backend + frontend 동시 기동, 로그 스트리밍
  exec docker compose --profile web up --remove-orphans
else
  exec docker compose --profile app run --rm jarvis
fi
