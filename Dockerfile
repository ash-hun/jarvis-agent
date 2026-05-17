FROM python:3.11-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY src/ src/

RUN uv sync --frozen --no-dev

# ── test stage ────────────────────────────────────────────────────────────────
FROM base AS test

RUN uv sync --frozen

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

RUN uv sync --frozen --extra web --no-dev

COPY . .

ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

CMD ["uv", "run", "jarvis", "--web", "--host", "0.0.0.0", "--port", "7777"]
