# Jarvis Web HUD API 명세

| 항목 | 값 |
|---|---|
| Last Updated | 2026-10-18 |
| Base URL | `http://localhost:7777` (Docker `web` 프로파일, nginx 가 `/api/`, `/ws`, `/brand.js`, `/manifest.json` 을 백엔드로 프록시하고 `/m/` 에서 모바일 앱 빌드 결과를 서빙. 포트는 127.0.0.1 에만 열리고 밖에서는 `tailscale serve` 로 들어온다) |
| 데이터 포맷 | JSON (UTF-8) |
| 인증 | 기본 없음. `JARVIS_SECURITY__API_KEYS` 가 비어 있지 않으면 `/api/*` 와 `/ws` 가 키를 요구한다 |

> `Last Updated`는 **문서 내용이 실제로 바뀐 날**만 적는다. 코드가 그대로인 채로 문서를
> 다시 생성했다면 이 값도 그대로다. 시각은 적지 않는다.

---

## 목차

1. [개요](#개요)
2. [공통 규약](#공통-규약)
3. [세부 API 명세](#세부-api-명세)
   - [GET /api/agents](#get-apiagents)
   - [GET /api/agenda](#get-apiagenda)
   - [POST /api/openloops/{loop_id}](#post-apiopenloopsloop_id)
   - [GET /api/push/vapid](#get-apipushvapid)
   - [PUT /api/push/subscriptions](#put-apipushsubscriptions)
   - [DELETE /api/push/subscriptions](#delete-apipushsubscriptions)
   - [POST /api/schedules/{name}](#post-apischedulesname)
   - [GET /api/sessions](#get-apisessions)
   - [POST /api/sessions](#post-apisessions)
   - [GET /api/sessions/{session_id}/messages](#get-apisessionssession_idmessages)
   - [DELETE /api/sessions/{session_id}](#delete-apisessionssession_id)
   - [POST /api/sessions/{session_id}/branch](#post-apisessionssession_idbranch)
   - [GET /api/slash-commands](#get-apislash-commands)
   - [GET /api/tools](#get-apitools)
   - [GET /api/voice/phrases/{name}](#get-apivoicephrasesname)
   - [GET /brand.js](#get-brandjs)
   - [GET /manifest.json](#get-manifestjson)
   - [WS /ws](#ws-ws)
4. [데이터 모델](#데이터-모델)

---

## 개요

Web HUD(`src/jarvis/ui/web/static/`)가 쓰는 백엔드 인터페이스다. 대화는 전부 WebSocket `/ws` 로 오가고, REST 는 화면 옆 카드(세션 목록, AGENDA, 도구 목록)를 채우거나 상태를 바꾸는 데만 쓴다. 정본은 백엔드의 세션 저장소(Postgres 또는 jsonl), 스케줄러, open loop 저장소이고 이 API 는 그 투영이다. 변경 알림 이벤트가 따로 없어서 프론트는 접속 직후, 응답이 끝날 때, 조작 직후, 그리고 1분마다 REST 를 다시 부른다.

소스: `src/jarvis/ui/web/server.py`, WebSocket 어댑터 `src/jarvis/ui/web/adapter.py`.

---

## 공통 규약

**에러 응답**

```json
{ "error": "사람이 읽을 수 있는 메시지" }
```

| 상태 코드 | 언제 |
|---|---|
| 200 | 정상 |
| 400 | 본문 값이 허용 범위 밖 (`status`, `enabled`) |
| 401 | 인증이 켜져 있는데 키가 없거나 틀림 (`/api/*`) |
| 404 | 대상 없음 (open loop, 스케줄, 읽기 문구) |
| 422 | FastAPI 가 본문을 JSON 객체로 못 읽음 |

**인증**: `JARVIS_SECURITY__API_KEYS` 에 키가 등록돼 있을 때만. `Authorization: Bearer <key>` 헤더 또는 `?token=<key>` 쿼리. `/ws` 는 쿼리만 받고 틀리면 close code `4401` 로 끊는다. 정적 셸(`/`, js, css)은 항상 열려 있다.

**페이지네이션**: 없음. 목록이 전부 작다. open loop 는 20개까지만 돌려준다.

**공통 헤더**: 없음. `Cache-Control: no-cache` 는 정적 셸과 `/brand.js`, `/manifest.json` 에만 붙고 `/api/*` 에는 붙지 않는다.

---

## 세부 API 명세

경로 알파벳순.

### GET /api/agents

이 서버에 뜬 최상위 에이전트 목록. main(JARVIS)이 첫 번째이고, 나머지는 정의 파일(`JARVIS_TEAM__DIR/<id>.yaml`) 이름순.

#### Endpoint

```
GET /api/agents
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `agents` | `Agent[]` | 아니오 | [Agent](#agent) 목록. 최소 main 하나 |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | 위 스키마 |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/api/agents
{"agents":[{"id":"main","name":"J.A.R.V.I.S.","description":"","quote":"Proof the Heart","palette":{"primary":"#5fc8e2","accent":"#f0b35f","background":"#02060c","nebula":["#3a5bff","#8a4dff","#ff6ad5"]},"main":true},{"id":"karen","name":"K.A.R.E.N.",...,"main":false}]}
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다. 정의 파일은 기동 때 한 번 읽는다. 파일을 고치면 서버를 다시 띄워야 목록이 바뀐다. 모델과 시스템 프롬프트는 내보내지 않는다.

---

### GET /api/agenda

AGENDA 카드가 보여줄 스케줄 작업, 열린 open loop, 최근 닫힌 open loop.

#### Endpoint

```
GET /api/agenda
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `schedules` | `Schedule[]` | 아니오 | 스케줄러가 없으면 빈 배열. 다음 실행이 가까운 순, 다음 실행이 없는 것(꺼짐, 만료)은 뒤 |
| `open_loops` | `OpenLoop[]` | 아니오 | 상태가 `open` 인 것만, 최신순 최대 20개. 기한이 지난 것은 응답 전에 닫혀 빠진다 |
| `closed_loops` | `ClosedLoop[]` | 아니오 | 상태가 `done`, `dismissed`, `expired` 인 것, 마지막으로 바뀐 순 최대 10개. 항목은 `id`, `description`, `status`, `updated_at`(epoch ms), `due_ms`, `agent`. 저장소가 꺼져 있으면 빈 배열 |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | 위 스키마 |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/api/agenda
{"schedules": [], "open_loops": [{"id": "e17dc364ae404c6c9d341b69a3a12b79", "description": "내일 오전 10시 회의의 구체적인 아젠다 및 발표 범위 확정", "due_ms": null, "created_at": 1791613276663, "origin_session": "default", "agent": "main"}], "closed_loops": [{"id": "a03c5e1f", "description": "보고서 보내기", "status": "done", "updated_at": 1791613276663, "due_ms": null, "agent": "main"}]}
```

#### 특이사항

**재호출**: 응답 전에 기한이 지난 open loop 를 `expired` 로 닫는다. 기한 뒤 `JARVIS_OPENLOOP__EXPIRE_AFTER_SEC`(기본 6시간)가 지났거나, 기한 없이 `JARVIS_OPENLOOP__MAX_AGE_SEC`(기본 7일)보다 오래된 것이다. 이미 닫힌 건 다시 보지 않으므로 몇 번 불러도 결과가 같다. 그 밖의 상태는 바꾸지 않는다. `next_run` 은 호출 시각 기준으로 계산하므로 같은 요청이라도 값이 흘러간다.

`next_run`, `run_until` 은 서버 로컬 시간대 오프셋이 붙은 ISO 8601 이다. 컨테이너의 `TZ` 를 따른다.

---

### POST /api/openloops/{loop_id}

open loop 하나를 완료 또는 무시로 닫거나, 닫힌 것을 다시 연다.

#### Endpoint

```
POST /api/openloops/{loop_id}
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `POST` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | `application/json` |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | `Content-Type` |

#### Request Body

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `status` | `"done" \| "dismissed" \| "open"` | 예 | 없음 | 바꿀 상태. `open` 은 닫힌 약속을 되살린다 |

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `loop_id` | path | string | 예 | 없음 | `GET /api/agenda` 의 `open_loops[].id` 또는 `closed_loops[].id` |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `id` | string | 아니오 | 요청한 id |
| `status` | string | 아니오 | 바뀐 상태 |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | `{"id", "status"}` |
| `400` | `status` 가 셋 중 하나가 아님 | `{"error": "status must be 'done', 'dismissed' or 'open'"}` |
| `404` | id 없음, 또는 open loop 저장소가 꺼져 있음 | `{"error": "open loop not found"}` |
| `409` | `open` 인데 기한이 `JARVIS_OPENLOOP__EXPIRE_AFTER_SEC` 넘게 지났거나, 기한 없이 `JARVIS_OPENLOOP__MAX_AGE_SEC` 보다 오래됨. 열자마자 다시 만료되므로 상태를 바꾸지 않는다 | `{"error": "open loop is past its due or age"}` |

#### 호출 예시

```bash
$ curl -s -X POST -H 'Content-Type: application/json' -d '{"status":"dismissed"}' http://localhost:7777/api/openloops/e17dc364ae404c6c9d341b69a3a12b79
{"id":"e17dc364ae404c6c9d341b69a3a12b79","status":"dismissed"}

$ curl -s -X POST -H 'Content-Type: application/json' -d '{"status":"maybe"}' http://localhost:7777/api/openloops/x
{"error":"status must be 'done', 'dismissed' or 'open'"}

$ curl -s -X POST -H 'Content-Type: application/json' -d '{"status":"done"}' http://localhost:7777/api/openloops/nope
{"error":"open loop not found"}
```

#### 특이사항

**재호출**: 멱등. 같은 id 에 같은 status 를 다시 보내도 결과가 같고 `updated_at` 만 갱신된다. 이미 `done` 인 것을 `dismissed` 로 바꾸는 것도 허용된다(마지막 호출이 이긴다). `open` 도 같다. 이미 열린 것을 다시 열어도 그대로 열려 있다. 되살린 약속은 기한과 생성 시각을 그대로 두므로 만료 규칙도 원래 기한 기준이다.

jsonl 저장소는 append-only 라 호출마다 한 줄이 붙고 읽을 때 마지막 줄이 이긴다.

---

### GET /api/push/vapid

모바일 앱(iOS 홈 화면 웹앱)이 Web Push 를 구독할 때 쓰는 VAPID 공개키.

#### Endpoint

```
GET /api/push/vapid
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `public_key` | string | 아니오 | base64url(패딩 없음), 65바이트 P-256 비압축 공개키 |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | `{"public_key"}` |
| `404` | 푸시가 꺼져 있음. `JARVIS_NOTIFY__WEBPUSH_VAPID_PUBLIC_KEY`, `..._PRIVATE_KEY`, `..._SUBJECT` 중 하나가 없거나 세션 저장소가 Postgres 가 아니다 | `{"error": "push disabled"}` |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/api/push/vapid
{"public_key":"BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U"}
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다. 키를 바꾸면 기존 구독이 전부 무효가 된다.

---

### PUT /api/push/subscriptions

Web Push 구독을 등록한다. 앱은 "알림 켜기"를 누를 때마다 다시 보낸다.

#### Endpoint

```
PUT /api/push/subscriptions
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `PUT` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | `application/json` |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | `Content-Type` |

#### Request Body

브라우저 `PushSubscription.toJSON()` 을 그대로 보낸다.

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `endpoint` | string | 예 | 없음 | 푸시 서비스 주소. `https://` 로 시작한다 |
| `expirationTime` | number \| null | 아니오 | null | 받기만 하고 쓰지 않는다 |
| `keys.p256dh` | string | 예 | 없음 | 본문 암호화 공개키 |
| `keys.auth` | string | 예 | 없음 | 본문 암호화 인증 비밀 |

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `ok` | boolean | 아니오 | 항상 `true` |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | `{"ok": true}` |
| `400` | 본문이 JSON 객체가 아니거나, `endpoint` 가 `https://` 가 아니거나, 키가 비었다 | `{"error": "endpoint must start with https://"}` |
| `404` | 푸시가 꺼져 있음 | `{"error": "push disabled"}` |

#### 호출 예시

```bash
$ curl -s -X PUT -H 'Content-Type: application/json' -d '{"endpoint":"https://web.push.apple.com/QH...","expirationTime":null,"keys":{"p256dh":"BN...","auth":"k8..."}}' http://localhost:7777/api/push/subscriptions
{"ok":true}
```

#### 특이사항

**재호출**: `endpoint` 를 자연 키로 upsert 한다(`push_subscriptions` 테이블의 기본 키). 몇 번 보내도 행은 하나이고 키와 `updated_at` 만 갱신된다. 인증이 켜져 있으면 그 키의 사용자 이름을 `user_id` 로 남긴다.

**발송**: `JARVIS_NOTIFY__KINDS` 의 알림(스케줄 결과, 🔔 등)을 구독 전부에 `{"title", "body", "tag"}` 로 보낸다. `title` 은 디스코드처럼 보낸 에이전트를 보인다. 에이전트 주색에 가장 가까운 색 원 이모지와 이름이다(예: `🟢 K.A.R.E.N.`, `🔵 J.A.R.V.I.S.`). 알림 종류 표시는 `body` 앞으로 간다(예: `⏱ 오늘의 LH 공고\n공고 2건`, `💭 Sir, ...`). 에이전트 아바타 주소가 설정돼 있으면 `icon` 도 준다(iOS 는 앱 아이콘만 보일 수 있다) `body` 는 1000자에서 자른다. `tag` 는 알림 id 라 같은 알림이 두 번 가도 iPhone 에는 하나로 보인다. 푸시 서비스가 404, 410 을 주면 그 구독을 지우고, 그 밖의 실패는 로그만 남기고 다시 보내지 않는다.

---

### DELETE /api/push/subscriptions

Web Push 구독을 지운다.

#### Endpoint

```
DELETE /api/push/subscriptions
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `DELETE` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | `application/json` |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | `Content-Type` |

#### Request Body

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `endpoint` | string | 예 | 없음 | 지울 구독의 endpoint |

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `ok` | boolean | 아니오 | 항상 `true` |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상. 없는 endpoint 도 200 | `{"ok": true}` |
| `400` | `endpoint` 가 없다 | `{"error": "endpoint is required"}` |
| `404` | 푸시가 꺼져 있음 | `{"error": "push disabled"}` |

#### 호출 예시

```bash
$ curl -s -X DELETE -H 'Content-Type: application/json' -d '{"endpoint":"https://web.push.apple.com/QH..."}' http://localhost:7777/api/push/subscriptions
{"ok":true}
```

#### 특이사항

**재호출**: 멱등. 이미 지운 구독을 다시 지워도 200 이다.

---

### POST /api/schedules/{name}

스케줄 작업을 켜거나 끈다.

#### Endpoint

```
POST /api/schedules/{name}
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `POST` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | `application/json` |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | `Content-Type` |

#### Request Body

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `enabled` | boolean | 예 | 없음 | `true` 켬, `false` 끔. 불리언이 아니면 400 |

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `name` | path | string | 예 | 없음 | `GET /api/agenda` 의 `schedules[].name` |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `name` | string | 아니오 | 요청한 이름 |
| `enabled` | boolean | 아니오 | 바뀐 값 |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | `{"name", "enabled"}` |
| `400` | `enabled` 가 불리언이 아님 | `{"error": "enabled must be true or false"}` |
| `404` | 이름 없음, 또는 스케줄러가 꺼져 있음 | `{"error": "schedule not found"}` |

#### 호출 예시

```bash
$ curl -s -X POST -H 'Content-Type: application/json' -d '{"enabled":false}' http://localhost:7777/api/schedules/nope
{"error":"schedule not found"}
```

#### 특이사항

**재호출**: 멱등. 같은 값을 다시 보내도 상태가 같다.

---

### GET /api/sessions

이 프로세스가 메모리에 들고 있는 세션 id 목록과 각 세션의 에이전트.

#### Endpoint

```
GET /api/sessions
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `sessions` | `string[]` | 아니오 | 세션 id. 기동 시 `default` 하나로 시작한다 |
| `agents` | `object` | 아니오 | 세션 id → 에이전트 id. 키는 `sessions` 와 같다 |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | 위 스키마 |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/api/sessions
{"sessions":["default","2e076b96"],"agents":{"default":"main","2e076b96":"karen"}}
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다.

저장소(DB)에 있는 세션이 아니라 **프로세스가 띄운 세션**만 나온다. 재시작하면 `default` 와 그 뒤 접속하거나 만든 것만 보인다. 저장된 전체 목록은 슬래시 명령 `/sessions` 가 보여준다.

---

### POST /api/sessions

새 세션을 만든다. id 는 서버가 정하고, 세션을 맡을 에이전트는 본문으로 고른다.

#### Endpoint

```
POST /api/sessions
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `POST` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | `application/json` (본문은 선택) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
|---|---|---|---|---|---|
| `agent` | string | 아니오 | `main` | `GET /api/agents` 의 id | 세션을 맡을 에이전트. 만든 뒤에는 바뀌지 않는다 |

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `session_id` | string | 아니오 | 8자리 hex. 이 id 로 `/ws?session_id=` 에 붙는다 |
| `agent` | string | 아니오 | 세션의 에이전트 id |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | `{"session_id", "agent"}` |
| `400` | 모르는 에이전트 | `{"error": "unknown agent: <id>"}` |

#### 호출 예시

```bash
$ curl -s -X POST http://localhost:7777/api/sessions -H 'content-type: application/json' -d '{"agent":"karen"}'
{"session_id":"2e076b96","agent":"karen"}
```

#### 특이사항

**재호출**: 멱등하지 않다. 부를 때마다 새 세션이 저장소와 메모리에 생긴다. 클라이언트가 재시도하면 빈 세션이 쌓이므로, 응답을 받은 뒤에만 `/ws` 에 붙이고 실패 시 다시 부르지 말 것. 지우는 것은 `DELETE /api/sessions/{session_id}`.

---

### GET /api/sessions/{session_id}/messages

세션의 대화 히스토리. CONVERSATION 복원에 쓴다.

#### Endpoint

```
GET /api/sessions/{session_id}/messages
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `session_id` | path | string | 예 | 없음 | 세션 id |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `messages` | `{role, text}[]` | 아니오 | `role` 은 `user` 또는 `assistant`. 도구 호출, 도구 결과, 빈 텍스트는 빠진다 |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상. 없는 세션도 200 에 빈 배열 | 위 스키마 |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/api/sessions/default/messages
{"messages": [{"role": "user", "text": "한 문장으로 자기소개 해줘"}, ...]}

$ curl -s http://localhost:7777/api/sessions/nope/messages
{"messages":[]}
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다.

없는 세션과 빈 세션을 구분하지 않는다. 텍스트는 마크다운 원문이고 렌더는 클라이언트 몫이다.

---

### DELETE /api/sessions/{session_id}

세션과 그 대화를 지운다. 메모리의 세션 객체와 저장소(jsonl 파일 또는 Postgres 행, 메시지는 cascade)가 함께 사라진다.

#### Endpoint

```
DELETE /api/sessions/{session_id}
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `DELETE` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `session_id` | path | string | 예 | 없음 | 지울 세션 |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `deleted` | string | 아니오 | 지운 세션 id |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 지웠거나 원래 없었다 | `{"deleted"}` |
| `409` | 그 세션에 붙어 있는 WebSocket 이 있다 | `{"error"}` |

#### 호출 예시

```bash
$ curl -s -X DELETE http://localhost:7777/api/sessions/2e076b96
{"deleted":"2e076b96"}
```

#### 특이사항

**재호출**: 멱등하다. 없는 세션을 지워도 `200` 이고 상태는 같다. 붙어 있는 연결이 있으면 `409` 로 거절하므로, 보고 있는 세션을 지우려면 먼저 다른 세션으로 옮긴다. `default` 도 지울 수 있고, 다음 접속 때 빈 세션으로 다시 생긴다.

---

### POST /api/sessions/{session_id}/branch

세션을 분기한다.

#### Endpoint

```
POST /api/sessions/{session_id}/branch
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `POST` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `session_id` | path | string | 예 | 없음 | 분기할 원본 세션 |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `session_id` | string | 아니오 | 새 세션 id |
| `parent_id` | string | 예 | jsonl 저장소면 원본 id. Postgres 저장소면 항상 `null` |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | `{"session_id", "parent_id"}` |

#### 호출 예시

```bash
$ curl -s -X POST http://localhost:7777/api/sessions/nope/branch
{"session_id":"2e076b96","parent_id":null}
```

#### 특이사항

**재호출**: 멱등하지 않다. 부를 때마다 새 세션이 생긴다.

분기는 부모와 같은 에이전트의 세션이다.

저장소가 Postgres(Docker 기본)면 분기가 아니라 **빈 새 세션 생성**과 같다. 원본 id 가 없어도 200 이고 히스토리를 복사하지 않는다(위 예시가 그 경우). 진짜 분기는 jsonl 저장소에서만 된다.

---

### GET /api/slash-commands

슬래시 명령 목록. 입력창 자동완성용. 같은 목록이 WS `connected` 메시지에도 들어 있어 HUD 는 이 엔드포인트를 쓰지 않는다.

#### Endpoint

```
GET /api/slash-commands
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `commands` | `{name, description}[]` | 아니오 | 이름순. 디스패처가 없으면 빈 배열 |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | 위 스키마 |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/api/slash-commands
{"commands": [{"name": "branch", "description": "[session_id] 세션을 분기"}, {"name": "cleanup", "description": "옛 데이터 현황과 삭제 (agents | stm, confirm 필요)"}, ...]}
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다. 승인된 절차(`/procedures approve`)가 늘면 목록도 는다.

---

### GET /api/tools

등록된 도구 목록. SYSTEM 카드의 TOOLS 가 쓴다.

#### Endpoint

```
GET /api/tools
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 설정 시 필요 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `session_id` | query | string | 아니오 | 없음 | 열린 세션 id. 주면 그 세션 에이전트가 쓰는 도구만(정의의 `tools`, 에이전트만 쓰는 `lh_notice` 등 포함, 늘 붙는 `ask_agent`, `remember_task_pattern` 포함), 없거나 열리지 않은 세션이면 앱 전체(에이전트만 쓰는 도구 제외) |

#### Response Body

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `tools` | `{name, description, approval}[]` | 아니오 | 이름순. `description` 은 첫 줄 160자. `approval` 은 실행 전 승인이 필요한 도구(`JARVIS_SECURITY__REQUIRE_APPROVAL_FOR`, 기본 `bash`, `write_file`, `edit_file`) |

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | 위 스키마 |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/api/tools
{"tools": [{"name": "bash", "description": "Execute a bash command and return stdout/stderr. Use with caution.", "approval": true}, {"name": "edit_file", "description": "Replace an exact string in a file. ...", "approval": true}, ...]}
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다. 승인된 절차는 `procedure_<name>` 도구로 여기 나타난다.

---

### GET /api/voice/phrases/{name}

미리 녹음한 읽기 문구 하나의 wav. 화면은 이벤트(웨이크워드, 도구 시작, Focus 전환 등)에 맞춰 합성 대신 이 파일을 재생한다.

#### Endpoint

```
GET /api/voice/phrases/{name}
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 공통 규약과 같다 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `audio/wav` (404 는 `application/json`) |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `name` | path | string | 예 | 없음 | 문구 이름. `connected.voice.phrases` 에 온 이름 중 하나 |

#### Response Body

wav 바이트. 문구 목록은 `JARVIS_VOICE__PHRASES_DIR` 의 `phrases.json` 이고, 목록에 있으면서 wav 파일도 있는 이름만 내준다.

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | wav |
| `404` | 모르는 이름이거나 문구 폴더를 설정하지 않음 | `{"error": "unknown phrase: hello"}` |

#### 호출 예시

```bash
$ curl -s -o wake_up.wav -w '%{http_code} %{content_type}\n' http://localhost:7777/api/voice/phrases/wake_up
200 audio/wav
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다. 문구 목록은 기동 때 한 번 읽으므로 파일을 바꿨으면 서버를 다시 띄운다.

---

### GET /brand.js

에이전트 정체성(이름, 명언, 팔레트)을 `window.BRAND` 에 넣는 스크립트. 정적 셸은 에이전트와 무관하고 정체성은 이 라우트로만 들어간다.

#### Endpoint

```
GET /brand.js
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 없음 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/javascript` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

JavaScript. `window.BRAND = {name, quote, palette: {primary, accent, background, nebula[]}}` 를 대입하고 CSS 변수를 설정한다. 값은 `JARVIS_BRAND__*` 설정.

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | 스크립트 |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/brand.js | head -c 200
window.BRAND = {"name": "J.A.R.V.I.S.", "quote": "Proof the Heart", "palette": {"primary": "#5fc8e2", "accent": "#f0b35f", "background": "#02060c", "nebula": ["#3a5bff", "#8a4dff", "#ff6ad5"]}};
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다. `Cache-Control: no-cache`.

---

### GET /manifest.json

PWA 매니페스트. 이름과 테마 색이 브랜드 설정에서 온다.

#### Endpoint

```
GET /manifest.json
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | `GET` |
| 인증 | 없음 |
| 요청 Content-Type | 없음 (본문 없음) |
| 응답 Content-Type | `application/json` |
| 필수 헤더 | 없음 |

#### Request Body

없음.

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| 없음 | | | | | |

#### Response Body

Web App Manifest. `name`, `short_name`, `description`, `start_url`(`./`), `scope`, `display`(`standalone`), `orientation`, `background_color`, `theme_color`, `icons`(192, 512, maskable).

#### 응답 코드

| 코드 | 의미 | 본문 |
|---|---|---|
| `200` | 정상 | 매니페스트 |

#### 호출 예시

```bash
$ curl -s http://localhost:7777/manifest.json | head -c 200
{"name":"J.A.R.V.I.S. · HUD","short_name":"J.A.R.V.I.S.","description":"Iron Man 스타일 개인 비서 에이전트 HUD","start_url":"./","scope":"./","display":"standalone","orientation":"any","ba
```

#### 특이사항

**재호출**: 상태를 바꾸지 않는다. nginx 가 `Cache-Control: no-cache` 를 붙인다.

---

### WS /ws

대화 채널. 연결 하나가 세션 하나에 붙고, 그 세션의 모든 에이전트 이벤트를 받는다. 같은 세션에 여러 연결이 붙으면 이벤트는 전부에게 가지만 **승인 요청은 마지막에 붙은 연결에만** 간다.

#### Endpoint

```
GET /ws?session_id=<id>&agent=<agent_id>&token=<key>   (Upgrade: websocket)
```

#### 호출 규약

| 항목 | 값 |
|---|---|
| Method | WebSocket |
| 인증 | 설정 시 `token` 쿼리 필수. 틀리면 accept 뒤 close `4401` |
| 에이전트 | 새 세션을 모르는 `agent` 로 열려 하면 accept 뒤 close `4404` |
| 메시지 포맷 | JSON 텍스트 프레임, 항상 `type` 필드. 바이너리 프레임은 웨이크워드용 오디오 하나뿐이다 |
| 필수 헤더 | 없음 |

#### Query / Path 파라미터

| 파라미터 | 위치 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `session_id` | query | string | 아니오 | `default` | 없으면 만든다 |
| `agent` | query | string | 아니오 | `main` | 새 세션을 맡을 에이전트. 이미 있는 세션(저장소 포함)은 저장된 에이전트로 열고 이 값은 무시한다 |
| `token` | query | string | 인증 시 예 | 없음 | API 키 |

#### 클라이언트 → 서버

| `type` | 필드 | 동작 |
|---|---|---|
| `user_message` | `text` | 슬래시 명령이면 디스패처가 처리하고 결과를 `agent_start`, `stream_delta`, `agent_end` 로 돌려준다. 남는 텍스트는 에이전트 프롬프트로. 비어 있으면 무시. `/focus` 로 시작하면 디스패처보다 먼저 Focus 가 받는다([Focus](#focus)) |
| `approval_response` | `id`, `approved`, `always` | `approval_request` 에 대한 답. 같은 `id` 에 먼저 온 답만 쓰고 나머지는 버린다. `always=true` 는 `approved=true` 일 때만 의미 있고 제안된 패턴을 세션 에이전트의 규칙 파일(`approvals/<agent_id>.yaml`)에 남긴다 |
| `proactive_feedback` | `id`, `accepted` | 🔔 에 대한 수락/무시. 임계치 학습기에 반영. 한 연결에서 같은 `id` 는 처음 한 번만 반영 |
| `reply_classify` | `kind`(`feedback`/`approval`), `id`, `text`, `context`, `has_always` | 키워드로 판정이 안 되는 짧은 답을 사고 모델로 분류. `feedback` 이면 `id` 는 🔔 의 `message_id`, `context` 는 🔔 본문. `approval` 이면 `id` 는 승인 요청 id, `context` 는 명령, `has_always` 는 항상 허용 패턴이 있는지. 결과는 `reply_classified`. 🔔 가 `accept`/`dismiss` 로 판정되면 서버가 바로 학습기에 반영한다(같은 `id` 는 한 번만). 승인은 판정만 돌려주고 승인 자체는 화면이 `approval_response` 로 보낸다 |
| `voice_tts_request` | `text`, `lang?`, `id?`, `source?`, `part?`, `full_text?` | 음성 합성. 서버가 마크다운 기호(제목, 강조, 목록, 표, 인라인 코드)를 지우고, 코드 블록과 URL 은 빼고, 링크는 글자만 남긴 뒤 읽는다. 서버 TTS 가 없거나 읽을 글자가 없으면 `voice_tts_audio{data:"", text}` 로 되돌려 브라우저가 읽게 한다. `id` 는 결과에 그대로 돌아온다. `source`(reply, filler, proactive, reminder, approval, approval_answer)는 무엇을 읽는지이고, 서버는 읽을 글을 외부 알림 채널(`spoken`)에도 보낸다. 서버가 이미 따로 보낸 `proactive`, `reminder` 는 보내지 않는다. 같은 세션의 같은 글은 10초 안에 다시 와도(화면을 여럿 열었거나 재요청) 한 번만 보낸다. 화면이 글을 문장 조각으로 나눠 보내면 조각마다 `part`(0부터)와 따로 된 `id` 를 붙이고, `part` 0 에만 나누기 전 원문 `full_text` 를 붙인다. 서버는 조각마다 `voice_tts_audio` 를 하나씩 돌려주고, 외부 알림은 `part` 0 에서 `full_text` 로 한 번만 보낸다 |
| `voice_spoken` | `phrase` | 화면이 녹음 문구를 재생했다. 서버가 그 문구의 문장(`phrases.json` 의 `text`)을 외부 알림 채널에 보낸다. 같은 세션의 같은 문장은 10초 안에 한 번만. 모르는 이름이면 무시 |
| `voice_stt_submit` | `data`(base64), `mime`, `sample_rate` | 서버 STT. 서버 STT 가 없으면 무시 |
| `abort` | 없음 | 진행 중인 에이전트 루프 중단 |
| (바이너리 프레임) | 16kHz mono int16 LE PCM | 웨이크워드 감지. `connected.voice.wake` 가 true 일 때만 받고, 아니면 버린다. 프레임 경계는 자유롭다(서버가 80ms 단위로 이어 붙인다). 화면은 모드와 상관없이 기다리는 동안(듣기, 읽기, 응답, 승인 중이 아닐 때) 보낸다 |

#### 서버 → 클라이언트

| `type` | 필드 | 언제 |
|---|---|---|
| `connected` | `session_id`, `agent`, `user`, `model`, `sessions[]`, `session_agents`, `active_agents[]`, `slash_commands[]`, `voice{stt_mode, stt_lang, phrases[], wake}`, `reply_classifier` | 접속 직후 한 번. `voice.phrases` 는 [읽기 문구](#get-apivoicephrasesname) 이름, `voice.wake` 는 웨이크워드 오디오를 받는지. `agent` 는 이 세션의 [Agent](#agent), `session_agents` 는 세션 id → 에이전트 id, `active_agents` 는 지금 루프가 도는 에이전트 id. `reply_classifier` 는 사고가 켜져 있어 `reply_classify` 를 쓸 수 있는지 |
| `agent_start` | `session_id`, `prompt`, `agent_name?` | 루프 시작. 서브 에이전트는 `agent_name` 이 있다 |
| `message_update` | `text_delta`, `thinking_delta` | 스트리밍 조각 |
| `stream_delta` | `text` | 슬래시 명령 결과 등 비스트림 텍스트 |
| `tool_execution_start` | `tool_call_id`, `tool_name`, `args` | 도구 실행 시작 |
| `tool_execution_end` | `tool_call_id`, `tool_name`, `is_error` | 도구 실행 끝 |
| `agent_end` | `session_id`, `final_message{usage}`, `turns`, `agent_name?`, `continues?` | 루프 끝. 루트면 입력을 다시 받는다. `continues: true` 는 `/focus` 안내 뒤 메인 에이전트가 이어 돈다는 뜻이라, 화면은 입력 잠금과 음성 요청 표시를 그대로 둔다 |
| `agent_error` | `message`, `code?` | 루프 실패 |
| `inner_thought` | `session_id`, `interpretation`, `decision`, `confidence`, `frame` | 요청 시점과 성찰 시점의 사고 1회 |
| `thought_route` | `session_id`, `think`, `p_think` | router(`JARVIS_THOUGHT__ROUTER_MODEL`)가 켜져 있을 때 요청마다 한 번, 응답보다 먼저. `think: true` 면 사고가 응답과 함께 돌고 그 결과는 다음 턴 시스템 프롬프트에 한 번 들어간다. `p_think` 는 맥락 없는 판정과 직전 두 턴을 넣은 판정 중 큰 값이고, router 가 답하지 못하면 null 이며 `think: true` 로 둔다 |
| `thought_end` | `session_id`, `ok` | `think: true` 로 띄운 사고가 끝났다. 응답보다 늦게 올 수 있다. 실패해도 `ok: false` 로 보낸다 |
| `agenda_changed` | `session_id` | 요청마다 사고와 따로 도는 AGENDA 판단이 약속을 새로 열거나(기한 갱신 포함) 닫았다. 응답보다 늦게 올 수 있다. 화면은 `GET /api/agenda` 로 다시 읽는다 |
| `proactive_message` | `session_id`, `text`, `kind`(`filler`/`proactive`/`answer`), `speak`, `message_id` | 먼저 건네는 말. `proactive` 면 피드백 대상. `answer` 는 대기 안내(`filler`) 뒤 뒤로 넘긴 작업이 끝났을 때의 답이고, 답은 스트림으로 이미 왔으므로 화면은 그리지 않는다(외부 알림 채널용). Focus 작업 중인 세션은 `proactive` 를 보내지 않는다(`filler`, `answer` 는 보낸다) |
| `approval_request` | `id`, `command`, `reason`, `always_pattern` | 도구 실행 승인 요청. 같은 세션의 열린 연결 전부에 보내고, 기다리는 중에 새로 붙은 연결에도 보낸다. 120초 안에 답이 없으면 거부로 처리 |
| `approval_resolved` | `id`, `timeout?` | 그 요청이 끝났다(어느 연결의 답, 또는 시간 초과). 아직 모달을 띄운 연결은 닫는다. 시간 초과면 `timeout: true` 이고, 에이전트 응답도 `승인 요청에 시간 안에 답이 없어 …` 로 거부(`승인이 거부되어 …`)와 구분된다 |
| `reminder` | `id`, `name`, `label`, `kind`, `agent`, `once`, `title`, `text`, `error`, `delayed_sec`, `fired_at`, `missed?` | 스케줄 실행 결과. 열린 연결 전부에 방송하고, 없으면 최근 20건을 쌓아 다음 접속 때 `missed: true` 로 보낸다. `label` 은 사람에게 보일 제목이다(사람이 붙인 이름, `/schedule` 이 붙인 이름이면 알림은 `알림`, 작업은 할 일 첫 줄). `kind: tool` 작업은 도구가 빈 글을 주면 보내지 않는다(새 공고가 없는 날 등) |
| `voice_tts_audio` | `data`(base64), `mime`, `text`, `id` | 합성 결과. `text` 는 실제로 읽은 글이다. `data` 가 비면 브라우저 TTS 로(`text` 는 기호를 지운 문장). `JARVIS_VOICE__SPEAK_ENGLISH=true` 면 JARVIS 세션의 한국어 글은 `source` 와 상관없이 LLM 이 짧은 영어로 옮겨 영어 TTS(JARVIS 목소리)로 읽고 `text` 에 그 영어를 준다. 옮기지 못하면(실패, 8초 초과) "Sir, I've put it on your screen." 을 읽는다. 다른 에이전트 세션은 원문 그대로다. 화면 글과 대화 기록은 한국어 그대로다. `id` 는 요청의 `id`(없었으면 null). 화면은 멈춘 읽기의 결과를 이 값으로 버린다 |
| `voice_stt_result` | `text`, `error?`, `unclear?`, `heard?` | 전사 결과. 받아 적은 글이 비었거나 확신도가 낮으면(말소리 없을 확률 > 0.6 또는 평균 로그 확률 < -1.0) `text` 를 비우고 `unclear: true` 와 받아 적은 글 `heard` 를 준다. 이때 서버가 이어서 되묻는 말을 `id` 없는 `voice_tts_audio` 로 보낸다(JARVIS 는 영어 "I'm sorry, sir. I didn't catch that.", 다른 에이전트는 한국어) |
| `voice_wake` | `score` | 바이너리 프레임의 오디오에서 "Jarvis" 를 들었다. 점수가 `JARVIS_VOICE__WAKE_THRESHOLD`(0.5) 이상인 첫 프레임에서 한 번 보내고, 그 뒤 1초(13프레임)는 다시 보내지 않는다 |
| `reply_classified` | `kind`, `id`, `verdict` | `reply_classify` 의 결과. `feedback` 은 `accept`/`dismiss`/`other`, `approval` 은 `allow`/`always`/`deny`/`unclear`. 사고 모델이 없거나 6초 안에 답하지 못하면 `other`, `unclear`. 항상 허용 패턴이 없는데 `always` 면 `allow` 로 낮춘다 |
| `agent_activity` | `active[]` | 어느 세션이든 루프가 시작하거나 끝나 일하는 에이전트 목록이 바뀔 때. 열린 연결 전부에 보내고 쌓아 두지 않는다. 먼저 시작한 순서, 같은 에이전트는 한 번 |
| `focus_state` | `session_id`, `state` | Focus 작업 상태 전체. `state.active=false` 면 Focus 종료. 켜져 있으면 `task_id`, `task`, `steps[{title, done}]`, `progress`(0~1), `eta_sec`(완료 단계가 없으면 null), `elapsed_sec`. 접속 직후 진행 중인 작업이 있으면 한 번 보낸다 |
| `focus_panel` | `session_id`, `area`(`reference`/`log`/`analysis`), `markdown`, `busy` | 한 영역의 마크다운 전체. `busy=true` 는 sub-agent 가 갱신 중. 접속 직후 진행 중인 작업이 있으면 세 영역을 한 번씩 보낸다 |
| `error` | `message` | TTS 오류 등 |

#### 호출 예시

```js
const ws = new WebSocket("ws://localhost:7777/ws?session_id=default");
ws.onmessage = (e) => console.log(JSON.parse(e.data).type);  // connected, agent_start, message_update, ...
ws.send(JSON.stringify({ type: "user_message", text: "안녕" }));
```

#### 특이사항

**재호출**: 같은 `session_id` 로 다시 붙으면 같은 세션이다. 재접속 자체는 멱등하다. `approval_request` 는 세션의 연결 전부가 받고 먼저 온 답이 채택되므로 탭을 여럿 열어도 같다. `user_message` 는 멱등하지 않다(보낼 때마다 한 턴). `reply_classify` 는 같은 답을 다시 보내면 모델을 다시 부르지만 🔔 학습은 연결당 `id` 하나에 한 번이다. 연결을 새로 열면 그 기록은 비므로 재접속 뒤 같은 `id` 를 다시 보내면 한 번 더 반영된다.

`reminder` 의 보류 큐는 메모리에만 있어 서버가 재시작되면 사라진다.

웨이크워드 감지기는 연결마다 하나이고 첫 오디오가 올 때 만든다. 앞 프레임을 기억하므로 재접속하면 처음부터 다시 듣는다.

#### Focus

`/focus <작업>` 은 이 세션의 Focus 작업을 시작하고, 안내(`agent_start`, `stream_delta`, `agent_end`)를 보낸 뒤 작업 문장을 에이전트 프롬프트로 이어 보낸다. 시작할 때 첫 분석과 단계 계획을 `JARVIS_FOCUS__READY_TIMEOUT_SEC`(30초)까지 기다린다. `/focus stop`(또는 `off`, `종료`)은 끝내고, `/focus` 만 보내면 현황을 텍스트로 돌려준다.

| 명령 | 이미 작업이 있을 때 | 작업이 없을 때 |
|---|---|---|
| `/focus <작업>` | 거절하고 진행 중인 작업을 알려 준다 | 시작 |
| `/focus stop` | 종료, `focus_state{active:false}` | "진행 중인 작업이 없습니다" |
| `/focus` | 진행률과 단계 | 시작 방법 안내 |

Focus 동안 매 턴 앞에서 분석 sub-agent 가, 뒤에서 기록과 진행 sub-agent 가 돌고 결과를 `focus_panel`, `focus_state` 로 보낸다. 조사 sub-agent 는 시작할 때와 분석이 조사할 검색어를 낼 때 돈다. 메인 에이전트의 시스템 프롬프트에는 작업, 단계, 직전 분석, 조사 요약이 붙는다.

**재호출**: 세션당 작업은 하나다. `~/.jarvis/focus/active/<session_id>` 를 배타적으로 만들어 보증하므로 `/focus <작업>` 을 동시에 두 번 보내도 하나만 시작한다. `/focus stop` 은 두 번째부터 아무것도 하지 않는다. 서버가 재시작돼도 활성 표시와 `state.json` 으로 작업을 되살리고, 접속하면 화면을 Focus 로 돌려놓는다. 기록은 `~/.jarvis/focus/<task_id>/`(`log.md`, `references.md`, `analysis.jsonl`, `state.json`)에 남고 종료해도 지우지 않는다.

---

## 데이터 모델

### Agent

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `id` | string | 아니오 | 에이전트 id. main 은 JARVIS, 나머지는 정의 파일 이름 |
| `name` | string | 아니오 | 워드마크이자 표시 이름 |
| `description` | string | 아니오 | 맡은 일. main 은 빈 문자열 |
| `quote` | string | 아니오 | 명언 |
| `palette` | object | 아니오 | `primary`, `accent`, `background`, `nebula[]` 색(#rrggbb) |
| `main` | boolean | 아니오 | JARVIS 인지 |

### Schedule

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `name` | string | 아니오 | 작업 이름. `slash-`, `once-` 로 시작하면 `/schedule` 로 만든 것 |
| `description` | string | 아니오 | 설명. 자동 생성일 수 있다 |
| `prompt` | string | 아니오 | 실행 프롬프트 앞 160자 |
| `schedule` | string | 아니오 | cron 식 |
| `kind` | `"reminder" \| "task" \| "tool"` | 아니오 | 알림, 에이전트가 도는 작업, 도구를 바로 부르는 작업 |
| `agent` | string | 아니오 | 작업을 실행하는 에이전트 id |
| `once` | boolean | 아니오 | 한 번만 도는 작업 |
| `enabled` | boolean | 아니오 | 켜짐 여부 |
| `next_run` | string | 예 | ISO 8601, 서버 시간대. 없으면 꺼졌거나 만료 |
| `run_until` | string | 예 | ISO 8601 만기 |

### OpenLoop

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `id` | string | 아니오 | 32자 hex |
| `description` | string | 아니오 | 약속이나 미완 작업 설명 |
| `due_ms` | integer | 예 | 기한(epoch ms). 사고가 "내일 10시" 같은 시각을 읽었을 때만 채워진다 |
| `created_at` | integer | 아니오 | epoch ms |
| `origin_session` | string | 예 | 감지된 세션 |
| `agent` | string | 아니오 | 약속을 감지한 세션의 에이전트 id. 에이전트 도입 전 약속은 `main` |

### Tool

| 필드 | 타입 | 널 허용 | 설명 |
|---|---|---|---|
| `name` | string | 아니오 | 도구 이름 |
| `description` | string | 아니오 | 첫 줄 160자 |
| `approval` | boolean | 아니오 | 실행 전 승인 필요 |
