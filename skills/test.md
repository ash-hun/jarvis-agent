---
name: test
description: Run the unit test suite via pytest
aliases: [t, pytest, ut]
---
`bash` 툴로 아래 명령을 실행해줘:

```
uv run pytest tests/unit/ -v --no-header --tb=short {{args}}
```

실행 후 다음 항목을 요약해줘:
1. 전체 테스트 수 / 통과 / 실패
2. 실패한 테스트가 있다면 — 테스트 이름과 오류 메시지
3. 최종 결과 (PASSED / FAILED)
