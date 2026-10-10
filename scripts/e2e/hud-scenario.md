# Web HUD 수동 확인 시나리오

Docker 로 띄운 Web HUD 에서 proactive 성찰, 승인 기억, 절차 학습을 눈으로 확인하는 절차다.
자동화 버전은 같은 디렉토리의 `hud_flow.py` 에 있다. 전체 10분쯤 걸린다.

## 준비

`.env` 에서 아래 값을 확인한다. 모델은 도구 호출과 JSON 출력이 되는 것이어야 한다. qwen3.5:0.8b 는 "생각" 에 토큰을 다 써서 안 된다.

```bash
JARVIS_LLM__PROVIDER=ollama
JARVIS_LLM__BASE_URL=http://host.docker.internal:11434
JARVIS_LLM__MODEL=gemma4:e4b
JARVIS_PROACTIVE__DAEMON_ENABLED=true
JARVIS_PROACTIVE__DAEMON_INTERVAL_SEC=90      # 확인용. 평소엔 900
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
3. 아무것도 하지 않고 기다린다. 주기 90초에 성찰 자체가 30~90초 걸리므로 2~3분 뒤 💭 줄이 한 번 더 뜨고(접혀 있다. 클릭하면 해석 전문), 바로 아래 🔔 proactive 발화와 "이 제안이 도움이 됐나요? 네 / 아니오 로 답해 주세요." 가 보인다.
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

## 실패로 봐야 하는 것

| 증상 | 볼 곳 |
|---|---|
| 💭 가 2~3분 간격으로 안 뜬다 | 백엔드 로그. `frame invalid` 면 모델 출력 형식 문제, `call failed` 면 Ollama 연결 문제 |
| 💭 는 뜨는데 🔔 가 안 뜬다 | 백엔드 로그의 `proactive silent: <이유>`. `empty utterance` 면 모델이 utterance 를 안 채운 것, `cooldown` 이면 300초 대기 |
| 승인 모달에 ALWAYS 가 없다 | 백엔드가 옛 소스. `docker compose --profile web up -d` 로 재생성 |
| 응답이 1분 넘게 안 온다 | 성찰과 겹쳐 Ollama 가 직렬 처리 중. 기다리면 온다. 주기를 900 으로 되돌리면 사라진다 |
| Ollama 가 모든 요청에 500 | 호스트 Ollama 서버와 러너 버전 불일치. `brew services restart ollama` |

## 정리

확인이 끝나면 주기를 되돌린다.

```bash
# .env: JARVIS_PROACTIVE__DAEMON_INTERVAL_SEC=900
docker compose --profile web up -d
```
