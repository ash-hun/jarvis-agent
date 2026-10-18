"""[scripts] 약속 중복 판정용 임베딩 비교. 바꿔 말한 같은 약속과 같은 주제의 다른 약속이 코사인으로 갈리는지 잰다."""

import json
import asyncio
import argparse
from pathlib import Path
from scripts.experiments.models import OLLAMA_URL

from jarvis.agent_layer.openloop.types import SAME_COSINE, same_loop
from jarvis.model_layer.embeddings import build_embedder, cosine
from jarvis.config import get_settings

DATASET = Path(__file__).parent / "datasets" / "loop_pairs.jsonl"
EMBEDDERS = {
    "bge-m3": ("ollama", "bge-m3"),
    "nomic-embed-text": ("ollama", "nomic-embed-text"),
    "text-embedding-3-small": ("openai", "text-embedding-3-small"),
    "none": ("", ""),  # 임베딩 없이 글자 규칙(정규화, 포함, bigram)만
}


async def run(name: str) -> dict[str, object]:
    provider, model = EMBEDDERS[name]
    pairs = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not provider:
        merged = [same_loop(p["a"], p["b"], None) for p in pairs]
        return {
            "embedder": name,
            "same_loop_acc": round(sum(m == p["same"] for p, m in zip(pairs, merged, strict=True)) / len(pairs), 3),
            "same_loop_false_merge": sum(m and not p["same"] for p, m in zip(pairs, merged, strict=True)),
        }
    secret = get_settings().llm.api_key
    embedder = build_embedder(
        provider,
        model,
        api_key=secret.get_secret_value() if secret and provider == "openai" else None,
        base_url=OLLAMA_URL if provider == "ollama" else None,
    )
    assert embedder is not None
    vectors = await embedder.embed([t for p in pairs for t in (p["a"], p["b"])])
    sims = [(cosine(vectors[2 * i], vectors[2 * i + 1]), p["same"]) for i, p in enumerate(pairs)]
    merged = [same_loop(p["a"], p["b"], s) for p, (s, _) in zip(pairs, sims, strict=True)]
    same = [s for s, flag in sims if flag]
    diff = [s for s, flag in sims if not flag]
    best = max(
        ((t / 100, sum((s >= t / 100) == flag for s, flag in sims) / len(sims)) for t in range(50, 100)),
        key=lambda x: x[1],
    )
    return {
        "embedder": name,
        "same_min": round(min(same), 3),
        "same_mean": round(sum(same) / len(same), 3),
        "diff_max": round(max(diff), 3),
        "diff_mean": round(sum(diff) / len(diff), 3),
        "gap": round(min(same) - max(diff), 3),
        f"acc_at_{SAME_COSINE}": round(sum((s >= SAME_COSINE) == flag for s, flag in sims) / len(sims), 3),
        "best_threshold": best[0],
        "best_acc": round(best[1], 3),
        # 실제 판정: 정규화 일치, 포함 관계, 코사인, 글자 bigram 겹침을 함께 본다
        "same_loop_acc": round(sum(m == p["same"] for p, m in zip(pairs, merged, strict=True)) / len(pairs), 3),
        "same_loop_false_merge": sum(m and not p["same"] for p, m in zip(pairs, merged, strict=True)),
        "pairs": [{"cos": round(s, 3), "same": flag} for s, flag in sims],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedder", action="append", choices=list(EMBEDDERS), required=True)
    for name in parser.parse_args().embedder:
        print(json.dumps(asyncio.run(run(name)), ensure_ascii=False))


if __name__ == "__main__":
    main()
