"""memory_eval 테스트 공용: 벤치마크 샘플 픽스처 경로."""

from pathlib import Path

BENCHMARKS_DIR = Path(__file__).parent / "benchmarks"
LONGMEMEVAL_SAMPLE = BENCHMARKS_DIR / "longmemeval_sample.json"
LOCOMO_SAMPLE = BENCHMARKS_DIR / "locomo_sample.json"
