"""[ion] Ion 설정. 환경변수 JARVIS_ION__* 로 받고, 푸시 키와 DSN 은 백엔드와 같은 변수를 되쓴다."""

import os
from collections.abc import Mapping
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from jarvis.ion.health_rules import Thresholds

# 백엔드와 같은 값을 쓰는 변수. Ion 전용 변수가 비어 있으면 이것을 읽는다
SHARED_ENV = {
    "postgres_dsn": "JARVIS_SESSION__POSTGRES_DSN",
    "vapid_private_key": "JARVIS_NOTIFY__WEBPUSH_VAPID_PRIVATE_KEY",
    "vapid_subject": "JARVIS_NOTIFY__WEBPUSH_SUBJECT",
}


class IonThresholds(BaseModel):
    """docs/ion-plan.md 의 표. 규칙 모듈의 Thresholds 와 같은 뜻이고 환경변수로 고칠 수 있다."""

    health_fail_count: int = 3
    restart_loop_count: int = 3
    restart_loop_window_ms: int = 600_000
    loop_lag_ms: float = 5_000.0
    loop_lag_count: int = 2
    memory_ratio: float = 0.85
    memory_window_ms: int = 300_000
    fail_streak: int = 3
    stale_ms: int = 7_200_000
    active_start_hour: int = 9
    active_end_hour: int = 21
    silent_ms: int = 86_400_000

    def rules(self) -> Thresholds:
        return Thresholds(
            health_fail_count=self.health_fail_count,
            restart_loop_count=self.restart_loop_count,
            restart_loop_window_ms=self.restart_loop_window_ms,
            loop_lag_ms=self.loop_lag_ms,
            loop_lag_count=self.loop_lag_count,
            memory_ratio=self.memory_ratio,
            memory_window_ms=self.memory_window_ms,
            fail_streak=self.fail_streak,
            stale_ms=self.stale_ms,
            active_hours=(self.active_start_hour, self.active_end_hour),
            silent_ms=self.silent_ms,
        )


class IonConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARVIS_ION__", env_nested_delimiter="__", extra="ignore")

    backend_url: str = "http://jarvis-backend:7777"
    backend_service: str = "jarvis-backend"  # compose 서비스 이름. 이 컨테이너만 다룬다
    docker_url: str = "http://docker-socket-proxy:2375"
    # 백엔드 /api 를 부르고 /ion 요청을 검사하는 접근 키. 백엔드의 api_keys 중 하나. 비우면 둘 다 검사하지 않는다
    access_key: SecretStr | None = None
    host: str = "0.0.0.0"
    port: int = 7778
    poll_sec: float = 15.0
    metrics_every: int = 4  # 지표, 컨테이너 통계, 구독 복사는 poll 네 번마다(60초)
    history: int = 120  # 관측 보관 수. 15초 × 120 = 30분
    data_dir: str = "~/.jarvis/ion"
    hud_url: str = "/"  # 알림을 눌렀을 때 여는 주소
    thresholds: IonThresholds = IonThresholds()
    postgres_dsn: str = ""  # 푸시 구독을 복사해 올 곳. 비우면 복사하지 않는다
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = ""


def load_config(environ: Mapping[str, str] | None = None) -> IonConfig:
    """설정을 읽고 비어 있는 공유 값은 백엔드 변수에서 채운다. 같은 환경이면 같은 설정이다."""
    env = environ if environ is not None else os.environ
    cfg = IonConfig()
    fill: dict[str, object] = {}
    if not cfg.postgres_dsn and env.get(SHARED_ENV["postgres_dsn"]):
        fill["postgres_dsn"] = env[SHARED_ENV["postgres_dsn"]]
    if cfg.vapid_private_key is None and env.get(SHARED_ENV["vapid_private_key"]):
        fill["vapid_private_key"] = SecretStr(env[SHARED_ENV["vapid_private_key"]])
    if not cfg.vapid_subject and env.get(SHARED_ENV["vapid_subject"]):
        fill["vapid_subject"] = env[SHARED_ENV["vapid_subject"]]
    return cfg.model_copy(update=fill) if fill else cfg
