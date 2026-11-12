#!/usr/bin/env bash
# 호스트 절전을 docker pause 로 재현해, 스케줄러가 지나친 cron 슬롯을 깨어난 뒤 한 번만 따라잡는지 실물에서 확인한다.
# 2분마다 도는 임시 reminder 를 메인 대화로 건네게 넣고, 첫 발화 뒤 5분 멈춰 슬롯 둘을 지나친 다음 홀수 분 30초에 깨운다.
# 그 시점의 직전 슬롯은 90초 전이라 예전 60초 규칙으로는 안 돌고, 따라잡기 규칙으로는 정확히 한 번 돈다.
# 두 번 돌려도 같다: 끝나면 임시 작업을 지우고 백엔드를 재시작한다. 시험 중 메인 대화에 "따라잡기 시험" 말이 두 번 남는다.
set -euo pipefail
cd "$(dirname "$0")/../.."

NAME=sim-catchup
TEXT="따라잡기 시험"
PAUSE_SEC=300

be() { docker compose exec -T jarvis-backend sh -c "$1"; }
count() {
  docker compose exec -T postgres sh -c \
    "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At -c \"select count(*) from jarvis_entries where type='proactive' and content->>'text'='$TEXT'\""
}
stamp() { date '+%H:%M:%S'; }
cleanup() {
  docker compose unpause jarvis-backend >/dev/null 2>&1 || true
  be "rm -f ~/.jarvis/schedules/$NAME.yaml"
  docker compose restart jarvis-backend >/dev/null 2>&1
  echo "[$(stamp)] cleanup: 임시 작업 제거, 백엔드 재시작"
}
trap cleanup EXIT

be "cat > ~/.jarvis/schedules/$NAME.yaml" <<YAML
name: $NAME
description: 스케줄러 따라잡기 시험
schedule: "*/2 * * * *"
kind: reminder
deliver: conversation
prompt: "$TEXT"
enabled: true
YAML
docker compose restart jarvis-backend >/dev/null
base=$(count)
echo "[$(stamp)] 임시 작업 등록, 백엔드 재시작. 기존 기록 $base 건"

# 첫 발화(기동 뒤 첫 짝수 분)를 기다린다. 2분 + 여유
for _ in $(seq 1 70); do
  [ "$(count)" -ge $((base + 1)) ] && break
  sleep 2
done
first=$(count)
[ "$first" -eq $((base + 1)) ] || { echo "[$(stamp)] FAIL: 첫 발화가 없다(기록 $first 건)"; exit 1; }
echo "[$(stamp)] 첫 발화 확인"

# 발화한 짝수 분의 30초에 멈춰 5분 뒤(홀수 분 30초)에 깨운다. 그 사이 슬롯 둘을 지나친다
while [ "$(date +%S)" -lt 30 ]; do sleep 1; done
docker compose pause jarvis-backend >/dev/null
echo "[$(stamp)] pause ${PAUSE_SEC}s (슬롯 2개 지나침)"
sleep "$PAUSE_SEC"
docker compose unpause jarvis-backend >/dev/null
echo "[$(stamp)] unpause. 직전 슬롯은 90초 전"
sleep 20
after=$(count)
echo "[$(stamp)] 깨운 뒤 20초 안 발화: $((after - first)) 건"

if [ "$after" -eq $((first + 1)) ]; then
  echo "PASS: 지나친 슬롯 둘 중 하나만 따라잡았다"
else
  echo "FAIL: 기대 1건, 실제 $((after - first)) 건"
  exit 1
fi
