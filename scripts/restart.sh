#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE="jarvis"
PROFILE="app"

cd "$PROJECT_DIR"

# docker compose run 으로 생성된 jarvis 컨테이너도 함께 정리
echo "[restart] Stopping $SERVICE..."
docker compose --profile "$PROFILE" down "$SERVICE" 2>/dev/null || true
docker ps -q --filter "name=${SERVICE}-run-" | xargs -r docker stop 2>/dev/null || true

if [[ "${1:-}" == "--build" ]]; then
  echo "[restart] Rebuilding image..."
  docker compose --profile "$PROFILE" build "$SERVICE"
fi

echo "[restart] Starting $SERVICE..."
exec docker compose --profile "$PROFILE" run --rm "$SERVICE"
