# Web HUD "JARVIS 연결 끊김 — 재연결 중..." (WebSocket 502)

## 증상

브라우저 Web HUD 상단에 **"⚠ JARVIS 연결 끊김 — 재연결 중..."** 이 계속 표시되고,
채팅/음성이 동작하지 않는다. 컨테이너는 모두 정상(`Up`, `healthy`)으로 보인다.

```text
NAME                       STATUS
jarvis-jarvis-backend-1    Up 10 hours (healthy)
jarvis-jarvis-frontend-1   Up 13 hours              # ← backend보다 먼저 떠 있음
jarvis-postgres-1          Up 13 hours (healthy)
```

## 원인

**nginx(frontend)가 죽은 옛 backend 컨테이너 IP를 캐싱**해서 `/ws`, `/api` 프록시가 502로 떨어진다.

nginx 로그에서 확인되는 결정적 단서:

```text
[error] connect() failed (113: Host is unreachable) while connecting to upstream,
  upstream: "http://172.26.0.4:7777/ws?session_id=default"
"GET /ws?session_id=default HTTP/1.1" 502
```

- backend **실제 현재** IP: `172.26.0.5`
- nginx가 물고 있는 IP: `172.26.0.4` (옛 IP) ❌

[`nginx/nginx.conf`](../../nginx/nginx.conf)의 `upstream` 블록은 **nginx 기동 시 단 한 번만** DNS를 resolve한다.

```nginx
upstream jarvis_backend {
    server jarvis-backend:7777;
}
```

frontend가 backend보다 먼저 떠 있는 상태에서 backend 컨테이너만 재기동/재생성되면
IP가 바뀌지만(`.4 → .5`), nginx는 시작 시점에 잡은 옛 IP를 계속 사용한다.
→ `502 Host is unreachable` → 브라우저 WebSocket 연결 실패 → "연결 끊김 — 재연결 중".

## 재발 조건

backend 컨테이너만 따로 재기동/재생성될 때마다 발생한다.

- `docker compose restart jarvis-backend`
- backend 이미지 리빌드 후 재기동
- backend healthcheck 실패로 인한 단독 재생성

## 즉시 복구

frontend(nginx)만 재시작하면 backend IP를 다시 resolve한다.

```bash
docker compose restart jarvis-frontend

# 복구 확인 (200이면 정상)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7777/api/sessions/default/messages
```

이후 브라우저 새로고침.

## 회피

backend와 frontend를 항상 같이 재시작한다. `scripts/restart.sh --web` 가 둘 다 올린다.

```bash
sh scripts/restart.sh --web
```

## 근본 해결 (적용됨)

> ✅ [`nginx/nginx.conf`](../../nginx/nginx.conf)에 아래 방식이 반영되어 있다. 정적 `upstream` 블록을 제거하고
> `resolver 127.0.0.11` + `set $backend` + 변수 `proxy_pass`로 매 요청 런타임 resolve한다.

nginx가 **요청마다 런타임에 DNS를 다시 resolve**하도록 변경한다.
Docker 내부 DNS(`127.0.0.11`)를 resolver로 쓰고 `proxy_pass`에 변수를 끼우면,
nginx가 upstream을 시작 시 고정하지 않고 매 요청마다 resolve한다.

```nginx
location /ws {
    resolver 127.0.0.11 valid=10s;
    set $backend jarvis-backend:7777;
    proxy_pass http://$backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    # ...
}
```

- `proxy_pass`에 **변수**(`$backend`)를 쓰는 것이 핵심 — 변수 없이 도메인을 직접 쓰면 시작 시 1회만 resolve한다.
- `/ws` 와 `/api` 두 location 모두 동일하게 적용해야 한다.
- 적용 후 frontend 재시작 필요.
