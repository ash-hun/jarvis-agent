---
sidebar_position: 6
title: 화면이 옛날 것이다
---

# 화면이 옛날 것이다

정적 파일은 네트워크 우선으로 받으므로 새로고침하면 반영된다. 그래도 옛 화면이 보이면 브라우저 개발자 도구의 Application 탭에서 서비스 워커를 지우고 다시 연다. nginx 와 백엔드는 모두 `Cache-Control: no-cache` 를 붙인다.
