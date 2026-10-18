"""router decision model(LLMClick pointer head)을 System One API 의 choice 질문으로 호스트에서 서빙한다."""

# Ollama 는 자체 decision head(Clef)만 받아 pointer head 를 올릴 수 없다. LLMClick 체크아웃의 환경에서 띄운다:
# cd ~/Desktop/personal_proj/llmclick
# uv run --frozen python ~/Desktop/personal_proj/jarvis_agent/scripts/router_server.py

import os
import time
import yaml
import torch
import uvicorn
import argparse
import threading
from typing import Any
from pathlib import Path
from pydantic import BaseModel
from core.pipeline import build
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from modeling.llm.methods.decision.base import items

MODEL_NAME = "router"
DEFAULT_PORT = 11435
DEFAULT_ROUTER_DIR = Path.home() / "Desktop/jarvis-agent-models/router"


class Question(BaseModel):
    type: str
    instructions: str
    criteria: dict[str, str]


class DecisionRequest(BaseModel):
    model: str
    state: str
    questions: dict[str, Question]


def _device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def create_app(router_dir: Path, device: str) -> FastAPI:
    config = build(yaml.safe_load((router_dir / "config.yaml").read_text())).config
    backbone, method = config.build_backbone(), config.build_method()
    # 모델 하나를 여러 요청 스레드가 같이 쓴다. MPS 는 동시 forward 를 보장하지 않는다
    lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        with backbone.loaded(device, router_dir):
            yield

    app = FastAPI(title="router decision model", lifespan=lifespan)

    @torch.no_grad()
    def probabilities(state: str, question: Question) -> dict[str, float]:
        options = list(question.criteria)
        # label 은 로더가 요구하는 필드일 뿐 추론에 쓰이지 않는다
        entry = items({"state": state, "questions": {"q": {**question.model_dump(), "label": options[0]}}})[0]
        with lock:
            scores = method.scores(backbone, [method.layout(backbone, entry)])[0]
            probs = method.head(backbone).probabilities(scores)[0]
        return {option: float(p) for option, p in zip(options, probs, strict=True)}

    @app.post("/v1/systemone")
    def systemone(request: DecisionRequest) -> dict[str, Any]:
        if request.model != MODEL_NAME:
            raise HTTPException(404, f"model {request.model!r} not found, this server serves {MODEL_NAME!r}")
        answers: dict[str, Any] = {}
        for name, question in request.questions.items():
            if question.type != "choice" or len(question.criteria) < 2:
                raise HTTPException(422, f"question {name!r}: only choice with two or more options is supported")
            started = time.perf_counter()
            probs = probabilities(request.state, question)
            answers[name] = {
                "type": "choice",
                "choice": max(probs, key=lambda option: probs[option]),
                "probabilities": probs,
                "latency_sec": round(time.perf_counter() - started, 4),
            }
        return {"model": MODEL_NAME, "answers": answers}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "model": MODEL_NAME, "device": device}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--router-dir", type=Path, default=Path(os.environ.get("ROUTER_DIR", DEFAULT_ROUTER_DIR)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--device", default=None, help="mps | cuda | cpu (기본: 쓸 수 있는 가속기)")
    args = parser.parse_args()
    uvicorn.run(create_app(args.router_dir, args.device or _device()), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
