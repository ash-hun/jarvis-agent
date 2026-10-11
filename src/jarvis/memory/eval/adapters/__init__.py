"""[memory] 외부 벤치마크 원본 JSON 을 BenchmarkQuestion 으로 바꾸는 어댑터를 이름으로 묶는다(데이터는 레포 밖)."""

from jarvis.memory.eval.adapters.locomo import load_locomo
from jarvis.memory.eval.adapters.longmemeval import load_longmemeval

LOADERS = {"longmemeval": load_longmemeval, "locomo": load_locomo}

__all__ = ["LOADERS", "load_locomo", "load_longmemeval"]
