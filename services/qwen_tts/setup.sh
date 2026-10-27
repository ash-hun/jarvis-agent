#!/bin/sh
# Qwen3-TTS 합성 서버 환경을 잠긴 버전으로 맞춘다. Apple silicon 전용. 다시 실행해도 같은 상태가 된다
set -eu
cd "$(dirname "$0")"
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
uv sync --frozen
.venv/bin/python -c "import mlx.core, mlx_audio.tts.utils"
echo "qwen-tts environment ready: $PWD/.venv/bin/python"
