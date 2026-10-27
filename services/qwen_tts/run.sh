#!/bin/sh
# 합성 서버를 띄운다. 모델은 HuggingFace 캐시에서 읽고 내려받지 않는다(처음 한 번은 HF_HUB_OFFLINE=0 으로 받는다)
set -eu
cd "$(dirname "$0")"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
exec .venv/bin/python -I server.py
