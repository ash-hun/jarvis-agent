# jarvis-agent 문서 사이트

Docusaurus. 문서는 `docs/` 아래 Markdown 이고 폴더 구조가 곧 목차다.

```bash
npm install
npm start        # http://localhost:3000/jarvis-agent/
npm run build    # build/ 에 정적 파일
```

다이어그램은 mermaid 코드블록으로 쓴다. 레포의 `docs/api_spec.md`, `docs/view_spec.md` 가 정본 명세이고 이 사이트는 설명이다.

`package.json` 의 `overrides` 가 mermaid 를 11.x 최신(11.17.2, 보안 패치 포함)으로 고정한다. 테마가 끌어오는 12.x 에서는 한 페이지의 두 번째 flowchart 가 그려지지 않았다(2026년 10월, theme-mermaid 3.10.2). 테마가 올라가면 고정을 풀고 `concepts/conversation/tools-and-approval` 과 `concepts/conversation/scheduling` 에서 도식이 다 나오는지 본다.

나머지 `overrides` 는 보안 패치용이다. 모두 Docusaurus 가 끌어오는 간접 의존성이고, 상위 패키지가 아직 패치 버전을 요구하지 않아 직접 올렸다(2026년 10월, Dependabot 알림 기준).

| 패키지 | 끌어오는 곳 | 고정 | 확인한 것 |
|---|---|---|---|
| `katex` | mermaid | 0.18.11 | mermaid 는 `^0.16.47` 을 요구하지만 수식 도표를 쓰지 않는다 |
| `lodash-es` | mermaid 파서(langium, chevrotain) | 4.18.1 | |
| `postcss-selector-parser` | cssnano 6 | 7.1.6 | 6.x 에는 패치가 없다. 빌드 페이지 수가 같다 |
| `serialize-javascript` | copy-webpack-plugin, css-minimizer | 7.1.2 | CommonJS `require` 그대로 |
| `tinypool` | `@docusaurus/core` SSG | 2.2.0 | 동적 `import()` 로 불러 ESM 전용 2.x 도 된다 |
| `uuid` | sockjs(개발 서버) | 11.1.1 | `require('uuid').v4` 그대로 |

상위 패키지가 패치 버전을 요구하게 되면 그 줄을 지우고 `npm install` 뒤 `npm audit` 으로 확인한다. `braces` 는 패치 버전이 없어 남아 있다(빌드 도구의 glob 처리 경로, 입력은 레포의 파일 패턴뿐).
