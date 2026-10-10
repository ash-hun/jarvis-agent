# jarvis-agent 문서 사이트

Docusaurus. 문서는 `docs/` 아래 Markdown 이고 폴더 구조가 곧 목차다.

```bash
npm install
npm start        # http://localhost:3000/jarvis-agent/
npm run build    # build/ 에 정적 파일
```

다이어그램은 mermaid 코드블록으로 쓴다. 레포의 `docs/api-spec.md`, `docs/screen-spec.md` 가 정본 명세이고 이 사이트는 설명이다.

`package.json` 의 `overrides` 가 mermaid 를 11.x 로 고정한다. 테마가 끌어오는 12.x 에서는 한 페이지의 두 번째 flowchart 가 그려지지 않았다(2026년 10월, theme-mermaid 3.10.2). 테마가 올라가면 고정을 풀고 `features/tools-and-approval` 과 `features/agenda` 에서 도식 두 개가 다 나오는지 본다.
