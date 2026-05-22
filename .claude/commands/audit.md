Perform a full project audit on the current working directory. This is a development kickoff analysis — understand what's built, what's incomplete, and what's worth building next.

## Step 1: Codebase Exploration

Spawn an Explore agent (subagent_type: Explore) with "very thorough" breadth to scan the entire project. The agent should collect:

1. **Full directory tree** — every file and folder under `src/`, `tests/`, config files, Dockerfiles, scripts
2. **Layer-by-layer implementation** — for each architectural layer, read the key files to understand what's actually implemented vs declared
3. **Stubs and gaps** — scan for `pass`, `TODO`, `FIXME`, `NotImplemented`, `raise NotImplementedError`, empty function bodies, `...` placeholders, stub comments
4. **Dependencies** — read `pyproject.toml`, `package.json`, `requirements.txt`, `Cargo.toml`, or equivalent; note optional/extra deps
5. **Test coverage** — list test files, count tests, identify untested modules
6. **Config / env vars** — what's declared in settings files, what's wired vs ignored

## Step 2: Analysis

After the Explore agent returns, synthesize its findings into the following structured report. Write in Korean with English technical terms mixed in.

---

### 📊 프로젝트 현황 요약

One-paragraph overview: project purpose, tech stack, maturity level (prototype / MVP / production-ready).

---

### ✅ 구현 완료 기능

A table per layer (or per major module) showing:
- Component name
- Status (✅ Complete / ⚠️ Partial / 🔴 Stub)
- Brief note on what's actually working

Group by architectural layer if the project has them (e.g., model_layer / agent_layer / core / ui). If the project has no formal layers, group by domain (auth / API / storage / UI).

---

### 🔴 미완성 / Stub 목록

For each incomplete item found:
- **File path and line number** (e.g., `src/foo/bar.py:42`)
- What the stub declares vs what it actually does
- Estimated complexity to complete (S / M / L)

---

### 🧪 테스트 현황

- Total test count and files
- Which modules have no tests
- Any test infrastructure gaps (no fixtures, real API calls in tests, etc.)

---

### 💡 추가할 수 있는 기능

Generate feature ideas based on what you see in the codebase — gaps, declared-but-unimplemented configs, obvious next steps, and industry-standard features for this type of project.

Organize into three priority tiers:

#### 🔴 High Priority (기존 인프라 활용, 즉시 착수 가능)
For each feature:
- **Feature name**
- Why it's high priority (existing infra exists, stub already declared, blocks other features)
- Affected files / modules
- Estimated effort (S=반나절, M=1-2일, L=3-5일)

#### 🟡 Medium Priority (새로운 기능 확장)
Same format. These require new code but fit naturally into the existing architecture.

#### 🟢 Low Priority (고급 기능 / 대규모 작업)
Same format. Architectural changes, integrations with external systems, or features that need significant new infra.

---

### 🗺️ 권장 로드맵

A phased plan (Phase 1 / 2 / 3) listing which features to tackle in which order, with a one-line rationale for each grouping. Format as a code block for readability:

```
Phase 1 — Completeness (기존 stub 완성)
  └─ Feature A (이유)
  └─ Feature B (이유)

Phase 2 — Power (핵심 기능 확장)
  └─ Feature C (이유)

Phase 3 — Scale (아키텍처 확장)
  └─ Feature D (이유)
```

---

## Output rules

- Be specific: name actual files, line numbers, class names — not vague descriptions
- Do not invent features the codebase gives no hint of wanting
- Keep each feature description to 2-3 sentences max
- If the project has a CLAUDE.md, use it to understand architectural constraints before suggesting features (never suggest things that violate stated hard rules)
- End with: "어떤 기능부터 시작할까요?" and offer to immediately start planning/implementing the highest-priority item
