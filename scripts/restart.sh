#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE="jarvis"
PROFILE="app"

cd "$PROJECT_DIR"

# --web 플래그: Web HUD 모드 선택
if [[ "${1:-}" == "--web" ]]; then
  SERVICE="jarvis-web"
  PROFILE="web"
  shift
fi

# docker compose run 으로 생성된 컨테이너도 함께 정리
echo "[restart] Stopping $SERVICE..."
docker compose --profile "$PROFILE" down "$SERVICE" 2>/dev/null || true
docker ps -q --filter "name=${SERVICE}-run-" | xargs -r docker stop 2>/dev/null || true

if [[ "${1:-}" == "--build" ]]; then
  echo "[restart] Rebuilding image..."
  docker compose --profile "$PROFILE" build "$SERVICE"
  shift
fi

echo "[restart] Starting $SERVICE..."
if [[ "$PROFILE" == "web" ]]; then
  exec docker compose --profile "$PROFILE" up --remove-orphans "$SERVICE"
else
  exec docker compose --profile "$PROFILE" run --rm "$SERVICE"
fi
