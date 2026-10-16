FROM python:3.11-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY src/ src/

RUN uv sync --frozen --no-dev

# ── test stage ────────────────────────────────────────────────────────────────
FROM base AS test

# web·scheduler extra까지 설치해야 Web HUD(fastapi)·스케줄러(croniter) 테스트가
# skip·수집 오류 없이 실제로 돈다.
RUN uv sync --frozen --extra web --extra scheduler

COPY tests/ tests/

ENV PYTHONPATH=/app/src
ENV JARVIS_DEBUG=true
ENV JARVIS_LLM__PROVIDER=faux
ENV JARVIS_LLM__MODEL=faux-model
ENV JARVIS_MEMORY__BACKEND=in_memory
ENV JARVIS_SESSION__PERSISTENCE_BACKEND=jsonl
ENV JARVIS_SESSION__SESSIONS_DIR=/tmp/jarvis/sessions
ENV JARVIS_MEMORY__SQLITE_PATH=/tmp/jarvis/memory.db
ENV JARVIS_SECURITY__REQUIRE_AUTH=false

CMD ["uv", "run", "pytest", "-v", "--no-header", "--tb=short"]

# ── runtime stage (TUI) ───────────────────────────────────────────────────────
FROM base AS runtime

COPY . .

ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

CMD ["jarvis"]

# ── runtime-web stage (Web HUD backend) ───────────────────────────────────────
FROM base AS runtime-web

# scheduler extra(croniter)가 없으면 스케줄러가 조용히 꺼지고 HUD Agenda 의 다음 실행 시각도 비는다.
# piper extra 는 영어 문장을 서버에서 읽는 음성(JARVIS_VOICE__ENGLISH_TTS_PROVIDER=piper)용이다.
RUN uv sync --frozen --extra web --extra scheduler --extra piper --no-dev

COPY . .

ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

CMD ["uv", "run", "jarvis", "--web", "--host", "0.0.0.0", "--port", "7777"]
