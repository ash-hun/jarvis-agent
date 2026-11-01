---
sidebar_position: 4
title: 설정이 안 먹는다
---

# 설정이 안 먹는다

`.env` 나 환경변수를 고쳤는데 동작이 그대로다. 이름을 잘못 적었거나, 고친 값이 실행 중인 프로세스 환경까지 가지 않은 경우가 대부분이다.

## 확인 순서

1. 변수 이름의 접두사와 구분자를 확인한다.
2. Docker 라면 `.env` 를 고친 뒤 컨테이너를 다시 만들었는지 본다.
3. 고친 값이 로그 설정(`JARVIS_LOG_LEVEL`, `LOG_FORMAT`)인지 본다.

## 원인과 해결

- 이름이 틀림: `JARVIS_THOUGHT__MODEL` 처럼 접두사 `JARVIS_` 로 시작하고 밑줄 두 개(`__`)로 이어야 한다
- Docker 에서 컨테이너를 다시 만들지 않음: compose 가 `.env` 를 읽어 컨테이너 환경에 넣는다. `.env` 를 고쳤으면 `docker compose up -d jarvis-backend` 로 컨테이너를 다시 만든다. `restart` 로는 환경이 바뀌지 않는다
- 접두사 없는 변수를 읽는 것처럼 보임: 중첩 설정은 `PATH` 처럼 접두사가 없는 환경변수를 읽지 않는다. 읽는 것처럼 보이면 버그다
- 로그 설정이 반영되지 않음: `JARVIS_LOG_LEVEL`, `LOG_FORMAT` 은 로거가 프로세스 환경변수에서 직접 읽는다. 로컬에서 `.env` 에만 적으면 반영되지 않으므로 `export JARVIS_LOG_LEVEL=DEBUG` 처럼 셸에서 준다. Docker 는 compose 의 `env_file` 이 넣어 준다

관련 문서: [서비스 설정 값](../reference/configuration.md)
