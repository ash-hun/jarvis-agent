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
# wake extra 는 "Jarvis" 웨이크워드(JARVIS_VOICE__WAKE_MODEL_DIR)용이다.
# discord extra 는 봇이 음성 채널에서 알림을 읽는 데 쓰고(JARVIS_NOTIFY__DISCORD_BOT_TOKEN), 재생에 ffmpeg 가 필요하다.
# voice extra 는 서버 STT(JARVIS_VOICE__STT_PROVIDER=whisper)와 서버 TTS(supertonic)용이다. 앱(iOS)이 녹음을 서버로 보낸다.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --extra web --extra scheduler --extra piper --extra wake --extra discord --extra voice --no-dev
# 음성 모델(supertonic, faster-whisper)을 볼륨(/root/.jarvis)에 받아 컨테이너를 다시 만들어도 다시 받지 않는다
ENV HF_HOME=/root/.jarvis/cache/huggingface

COPY . .

ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

CMD ["uv", "run", "jarvis", "--web", "--host", "0.0.0.0", "--port", "7777"]
