# Web HUD 수동 확인 시나리오

Docker 로 띄운 Web HUD 에서 proactive 성찰, 승인 기억, 절차 학습, Full-voice 알림과 KAREN 흐름을 눈으로 확인하는 절차다.
자동화 버전은 같은 디렉토리의 `hud_flow.py` 에 있다. 1~3 은 10분쯤, 4 는 15분쯤 걸린다.

## 준비

`.env` 에서 아래 값을 확인한다. 메인 모델은 도구 호출이 되는 것이어야 한다(qwen3.5:0.8b 는 안 된다). 사고 모델은 `JARVIS_THOUGHT__MODEL=gemma4:e2b-it-qat` 로 분리한다(0.8b 급은 프레임 JSON 을 못 지킨다).

```bash
JARVIS_LLM__PROVIDER=ollama
JARVIS_LLM__BASE_URL=http://host.docker.internal:11434
JARVIS_LLM__MODEL=gemma4:e4b
JARVIS_THOUGHT__MODEL=gemma4:e2b-it-qat
JARVIS_PROACTIVE__DAEMON_ENABLED=true
JARVIS_PROACTIVE__DAEMON_INTERVAL_SEC=120     # 기본값과 같다
```

```bash
docker compose --profile web up -d        # .env 를 바꿨으면 restart 가 아니라 up -d
open http://localhost:7777
docker compose --profile web logs -f jarvis-backend | grep "\[Thought\]"   # 성찰 결과를 같이 본다
```

슬래시 명령을 입력할 때 자동완성 피커가 열리면 첫 Enter 는 항목 선택이다. Enter 를 한 번 더 누른다.

## 1. 성찰이 먼저 말을 거는가 (약 3분)

1. 입력: `내일 오전 10시에 팀에 배포 결과를 공유하기로 했어. 기억해줘`
2. 기대: 💭 줄(act · 100%) 뒤에 본 응답. 모델이 없는 도구(`calendar_tool` 등)를 부르면 CONVERSATION 에 `Error` 한 줄이 뜨고 텍스트로 회복한다. 모델의 환각이지 버그가 아니다.
3. 아무것도 하지 않고 기다린다. 주기 120초에 성찰 자체가 30~90초 걸리므로 3~4분 뒤 💭 줄이 한 번 더 뜨고(접혀 있다. 클릭하면 해석 전문), 바로 아래 🔔 proactive 발화와 "이 제안이 도움이 됐나요? 네 / 아니오 로 답해 주세요." 가 보인다.
4. 입력창에 `아니오` 를 보낸다. `피드백: 무시` 한 줄이 뜨고 LLM 으로는 가지 않는다. 다음 성찰은 💭 만 뜨고 🔔 는 뜨지 않는다. 쿨다운 300초가 걸려 있고, 임계치가 0.6 에서 0.65 로 올라갔기 때문이다.
5. 오른쪽 AGENDA 의 OPEN LOOPS 에 "배포 결과 공유" 가 들어 있는지 본다.

## 2. 승인 기억 (약 1분)

1. 입력: `bash 로 echo hello 실행해줘`
2. 기대: 승인 모달에 `ALWAYS · echo hello`, `ALLOW`, `DENY` 세 버튼. **ALWAYS** 를 누른다.
3. 같은 입력을 한 번 더 보낸다. 모달 없이 바로 실행된다.
4. 입력: `bash 로 ls 실행해줘`. 다른 패턴이라 다시 묻는다. 이번엔 ALLOW.
5. 규칙 파일에는 `echo hello` 만 남아 있어야 한다.

```bash
docker compose --profile web exec jarvis-backend cat /root/.jarvis/approvals.yaml
```

## 3. 절차 학습 (약 3분)

1. 도구를 3번 이상 쓰게 하는 입력: `현재 디렉토리의 md 파일 목록을 보고, README.md 앞 20줄을 읽고, 마지막에 echo done 을 실행해서 요약해줘`
2. 응답이 끝나면 `/procedures learn`. 기대: `초안 저장: <name>`.
3. `/procedures learn` 을 한 번 더 보낸다. 기대: `새로 배울 구간이 없습니다`. 같은 구간은 두 번 배우지 않는다.
4. `/procedures approve <name>`. 오른쪽 SYSTEM 의 도구 목록에 `procedure_<name>` 이 추가된다.
5. `/<name>` 으로 호출하면 절차 본문이 프롬프트로 들어가 같은 작업을 다시 수행한다.

## 4. Full-voice: 중복 알림, 약속 되살리기, KAREN 자격, 새 공고 알림 (약 15분)

준비: `.env` 에 `JARVIS_NOTIFY__DISCORD_WEBHOOK_URL` 이 있어야 디스코드 확인이 된다. 음성 모델(`./models`)이 없으면 브라우저 음성으로 읽는다. 메인 모델은 도구 호출이 되는 것이어야 한다. 디스코드 채널을 옆에 띄워 둔다.

### 4-1. 같은 세션을 연 두 화면이 같은 말을 읽어도 디스코드에는 한 번

1. 브라우저 탭 두 개로 `http://localhost:7777` 을 열고 둘 다 SESSIONS 에서 같은 세션(`default`)을 고른다.
2. 두 탭 모두 헤더에서 `FULL-VOICE` 를 누른다. 마이크 권한을 허용한다.
3. 한 탭의 구체를 누르고 말한다: "오늘 날짜 알려줘"
4. 기대: 두 탭이 같은 답을 각자 읽는다. 디스코드에는 `🔊 J.A.R.V.I.S.` 메시지가 **한 번만** 뜬다.
5. 10초 넘게 지난 뒤 같은 질문을 다시 한다. 디스코드에 한 번 더 뜬다(같은 글은 10초 안에서만 거른다).

### 4-2. 잘못 닫힌 약속을 되살린다

1. 말한다: "내일 오후 3시까지 팀장님께 보고서 보내야 해"
2. 기대: AGENDA 의 OPEN LOOPS 에 보고서 항목이 기한과 함께 들어온다(응답보다 늦게 올 수 있다).
3. 말한다: "보고서는 이미 보냈어"
4. 기대: 그 약속이 OPEN LOOPS 에서 빠지고 아래 `CLOSED 01` 줄이 생긴다. AGENDA 판단이 닫지 않았으면 ✓ 를 눌러 닫는다.
5. `CLOSED` 줄을 눌러 펼친다. 항목에 `완료 · HH:MM` 이 보인다.
6. ↺ 를 누른다. 기대: OPEN LOOPS 로 돌아오고 ACTIVITY 에 `↺ 되살림 · ...` 한 줄. 새로고침해도 열려 있다.
7. (선택) 기한이 6시간 넘게 지난 약속의 ↺ 는 ACTIVITY 에 빨간 `기한이 지나 되살리지 않음` 이 뜨고 CLOSED 에 남는다.

### 4-3. KAREN 이 가구원수, 수급자, 대학생으로 신청 가능성을 가른다

1. SESSIONS 에서 `K.A.R.E.N.` 칩을 눌러 KAREN 세션을 연다. `FULL-VOICE` 를 켠다.
2. 말한다: "나 무주택이고 미혼이야. 연소득 육천만 원, 스물여덟 살, 가구원은 나 혼자고 수급자 아니고 대학생도 아니야"
3. 기대: KAREN 이 `housing_profile` 로 저장했다고 답한다. 입력창에 `/housing` 을 보내면 `가구원수: 1명`, `수급자: 아니오`, `대학생: 아니오` 가 보인다.
4. 말한다: "현금 오천만 원, 월 백오십만 원으로 맞는 공고 찾아줘"
5. 기대: 결과를 읽는다(길다). 화면의 결과에서 영구임대, 국민임대가 `신청 가능성이 낮아 뒤로 보낸 공고` 줄에 있다.
6. 말한다: "가구원 세 명으로 바꿔줘" 뒤에 4번을 다시 말한다.
7. 기대: 같은 공고가 `신청 가능성 확인 필요` 로 올라오고 사유에 `3인 가구 기준은 더 높아 공고문으로 확인한다` 가 붙는다.
8. 끝나면 입력창에 `/housing set 가구원수=모름` 을 보내 원래대로 돌린다(도구는 값을 비우지 못한다).

### 4-4. 새 LH 공고 알림

1. 스케줄 파일을 넣는다. 확인용으로 5분마다 돌게 한다.

```bash
docker compose --profile web exec jarvis-backend sh -c 'mkdir -p /root/.jarvis/schedules && cat > /root/.jarvis/schedules/housing-watch.yaml' <<'YAML'
name: housing-watch
description: 새 LH 공고
schedule: "*/5 * * * *"
kind: tool
agent: karen
tool: housing_watch
args: {regions: "서울,경기", quiet: true}
prompt: ""
YAML
docker compose --profile web restart jarvis-backend
```

2. 기대: AGENDA 의 UPCOMING 에 `새 LH 공고` 가 `K.A.R.E.N.` 라벨로 보인다.
3. 다음 5분 경계에 화면에 🔔 `housing-watch` 와 디스코드에 `⏱ housing-watch` "지금 공고중 N건(서울, 경기)을 기준으로 삼았다" 가 뜬다. Full-voice 면 소리 내어 읽는다.
4. 그다음 5분 경계에는 아무것도 뜨지 않는다(새 공고가 없으면 알리지 않는다). 백엔드 로그에 `had nothing to report` 가 남는다.
5. 새 공고가 생긴 경우를 보려면 본 공고 기록에서 하나를 뺀다. 다음 경계에 `새 LH 공고 1건` 이 링크와 함께 한 번 오고, 그다음 경계는 다시 조용하다.

```bash
docker compose --profile web exec jarvis-backend sh -c 'python - <<PY
import json, glob
f = glob.glob("/root/.jarvis/housing/seen/*.json")[0]
d = json.load(open(f)); d["ids"] = d["ids"][1:]; json.dump(d, open(f, "w"))
PY'
```

6. 확인이 끝나면 `schedule` 을 `"0 9 * * *"` 로 바꾸거나 AGENDA 스위치로 끈다.

## 실패로 봐야 하는 것

| 증상 | 볼 곳 |
|---|---|
| 💭 가 2~3분 간격으로 안 뜬다 | 백엔드 로그. `frame invalid` 면 모델 출력 형식 문제, `call failed` 면 Ollama 연결 문제 |
| 💭 는 뜨는데 🔔 가 안 뜬다 | 백엔드 로그의 `proactive silent: <이유>`. `empty utterance` 면 모델이 utterance 를 안 채운 것, `cooldown` 이면 300초 대기 |
| 승인 모달에 ALWAYS 가 없다 | 백엔드가 옛 소스. `docker compose --profile web up -d` 로 재생성 |
| 응답이 1분 넘게 안 온다 | 성찰과 겹쳐 Ollama 가 직렬 처리 중. 기다리면 온다 |
| 디스코드에 🔊 가 화면 수만큼 뜬다 | 두 탭이 같은 세션인지 본다. 세션이 다르면 따로 보내는 것이 맞다 |
| UPCOMING 에 `새 LH 공고` 가 없다 | 백엔드 로그의 `[SchedulerLoader] Failed to load`. YAML 들여쓰기, `kind: tool` 철자 |
| `⏱ housing-watch (실패)` | 백엔드 로그의 `Tool task 'housing-watch' failed`. `unknown tool` 이면 `team/karen.yaml` 의 tools 에 `housing_watch` 가 없는 것 |
| Ollama 가 모든 요청에 500 | 호스트 Ollama 서버와 러너 버전 불일치. `brew services restart ollama` |

