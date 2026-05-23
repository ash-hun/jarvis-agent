---
name: jarvis-add-skill
description: "Jarvis 내부 스킬(명령 매크로) 신규 추가. ~/.jarvis/skills/*.md 파일 생성, SkillRegistry 포맷 적용, 동작 검증까지 안내. Triggers on: 'jarvis skill 추가', 'add jarvis skill', '스킬 만들어', 'new skill', '커맨드 매크로 추가'."
user-invocable: true
argument-hint: "<skill-name> [설명]"
---

# Jarvis Add Skill

Jarvis 내부 SkillRegistry에 새 스킬(명령 매크로)을 추가한다.
스킬은 `/skill-name args` 형태로 Jarvis TUI/Web HUD에서 호출되며,
`{{args}}`를 실제 입력으로 치환한 프롬프트를 에이전트에게 전달한다.

## 전제 지식

**Jarvis 스킬 파일 포맷** (`~/.jarvis/skills/<name>.md`):

```markdown
---
name: <skill-name>           # /로 호출할 이름
description: <한 줄 설명>
aliases: [단축명1, 단축명2]   # 선택
---
에이전트에게 전달할 프롬프트.
{{args}} 위치에 사용자 입력이 치환된다.
```

**SkillRegistry 동작** (`src/jarvis/core/skills/registry.py`):
- `load_directory("~/.jarvis/skills/")` 에서 자동 로드
- `expand("/skill-name some args")` → `content.replace("{{args}}", "some args")`
- 중복 name은 first-registration-wins (강제 덮어쓰기 불가)

## 스킬 추가 절차

### Step 1 — 스킬 명세 수집

사용자에게 아래를 확인한다 (argument로 일부 제공됐으면 그걸 활용):

1. **스킬 이름**: Jarvis 내에서 `/name`으로 호출할 식별자
2. **목적**: 이 스킬이 에이전트에게 무엇을 하도록 하는가
3. **입력**: `{{args}}`에 들어올 내용 (없으면 고정 프롬프트)
4. **단축 aliases**: 선택 사항

### Step 2 — 파일 생성

`~/.jarvis/skills/<name>.md` 를 Write 툴로 생성한다.

**좋은 프롬프트 작성 원칙**:
- 에이전트가 할 **행동**을 구체적으로 기술
- `{{args}}`는 사용자 입력이 자연스럽게 삽입되는 위치에 배치
- 출력 포맷이 정해져 있으면 명시 (예: "결과를 마크다운 표로 정리해줘")
- 필요한 도구 힌트 포함 (예: "bash 툴로", "read_file 툴로")

**예시**:
```markdown
---
name: summarize
description: 파일 내용을 요약
aliases: [sum, s]
---
`read_file` 툴로 {{args}} 파일을 읽고 아래 형식으로 요약해줘:
1. 핵심 목적 (1문장)
2. 주요 컴포넌트/섹션 목록
3. 주의할 점이나 TODO
```

### Step 3 — 동작 검증

파일 생성 후 Jarvis에서 실제로 호출 가능한지 확인:

```bash
# 1. 파일이 올바르게 생성됐는지 확인
ls ~/.jarvis/skills/
cat ~/.jarvis/skills/<name>.md

# 2. Python으로 파싱 검증 (Jarvis 설치된 경우)
python3 -c "
from jarvis.core.skills.registry import SkillRegistry, _parse_skill_file
from pathlib import Path
skill = _parse_skill_file(Path('~/.jarvis/skills/<name>.md').expanduser())
print('name:', skill.name)
print('aliases:', skill.aliases)
print('content preview:', skill.content[:100])
"
```

### Step 4 — 검증 완료 후 안내

성공하면 사용자에게 아래를 알려준다:

```
✓ 스킬 생성 완료: ~/.jarvis/skills/<name>.md
  호출: /<name> [args]
  단축: /<alias> [args]   (aliases가 있는 경우)

  Jarvis 재시작 없이 사용 가능 (watch_files=true 기본값).
  단, 현재 실행 중인 세션은 재시작 필요.
```

## 주의사항

- `name`은 기존 등록된 스킬과 중복 금지 — `/help` 로 현재 목록 확인
- `aliases`도 중복 불가 (registry에서 alias → name 매핑 충돌)
- `{{args}}`가 없는 스킬은 항상 동일 프롬프트 전송 (고정 매크로)
- `~/.jarvis/skills/` 경로가 없으면 `mkdir -p` 로 먼저 생성
