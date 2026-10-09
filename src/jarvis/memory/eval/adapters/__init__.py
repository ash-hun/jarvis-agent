"""외부 벤치마크 어댑터. 원본 JSON 을 BenchmarkQuestion 으로 바꾼다. 데이터는 레포 밖에 둔다."""

from jarvis.memory.eval.adapters.locomo import load_locomo
from jarvis.memory.eval.adapters.longmemeval import load_longmemeval

LOADERS = {"longmemeval": load_longmemeval, "locomo": load_locomo}

__all__ = ["LOADERS", "load_locomo", "load_longmemeval"]
