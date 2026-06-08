from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerConfig(BaseModel):
    """MCP 서버 연결 설정. BaseModel (list 항목이라 BaseSettings 불필요)."""

    name: str
    transport: Literal["stdio", "http"] = "stdio"
    command: list[str] = Field(default_factory=list)  # stdio transport용 명령
    url: str | None = None  # http/sse transport용 엔드포인트
    env: dict[str, Any] = Field(default_factory=dict)
    timeout: float = 30.0  # 연결/툴 호출 타임아웃(초) — 응답 없는 서버가 startup을 막지 않도록
    headers: dict[str, str] = Field(default_factory=dict)  # http transport용 커스텀 헤더
    auth_token: SecretStr | None = None  # http transport용 Bearer 토큰 (Authorization 헤더로 변환)


class WebSearchConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    brave_api_key: SecretStr | None = None  # 미설정 시 DuckDuckGo fallback


class LLMProviderConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5"
    api_key: SecretStr | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0


class SecurityConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    require_auth: bool = True
    allowed_roles: list[str] = Field(default_factory=lambda: ["user", "admin"])
    dangerous_commands: list[str] = Field(
        default_factory=lambda: ["rm -rf", "sudo", "curl | bash", "wget | bash", "> /dev/sda"]
    )
    require_approval_for: list[str] = Field(default_factory=lambda: ["bash", "write_file", "edit_file"])
    input_max_length: int = 10_000
    jwt_secret: SecretStr | None = None
    jwt_algorithm: str = "HS256"


class MemoryConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    backend: Literal["in_memory", "postgres"] = "postgres"
    postgres_dsn: str | None = None  # None이면 session.postgres_dsn fallback
    window_size: int = 50
    compaction_threshold: int = 100_000


class SessionConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    persistence_backend: Literal["jsonl", "postgres"] = "jsonl"
    sessions_dir: str = "~/.jarvis/sessions"
    postgres_dsn: str | None = None


class UIConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mode: Literal["tui", "web"] = "tui"
    theme: str = "dark"
    show_thinking: bool = True


class PluginConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    plugins_dir: str = "~/.jarvis/plugins"
    skills_dir: str = "~/.jarvis/skills"
    tools_dir: str = "~/.jarvis/tools"
    watch_files: bool = True


class SchedulerConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = True
    schedules_dir: str = "~/.jarvis/schedules"


class AgentConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = True
    agents_dir: str = "~/.jarvis/agents"


class ThoughtConfig(BaseSettings):
    """Inner Thought Engine 설정 (Tier 0). 기본 on — JARVIS_THOUGHT__ENABLED=false로 끈다."""

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = True
    model: str = ""  # 비우면 메인 LLM 모델, 지정 시 별도 모델
    # 사고 모델을 메인과 완전 분리 (예: 메인=anthropic, 사고=ollama 로컬).
    # 비우면 메인 LLM의 provider/key/base_url을 그대로 상속.
    provider: str = ""
    api_key: SecretStr | None = None
    base_url: str = ""
    prompt_path: str = "~/.jarvis/inner_thought.md"
    confidence_threshold: float = 0.6  # Tier 1 게이팅용 (Tier 0은 기록만)
    proactive_cooldown_sec: int = 300  # Tier 1 발화 쿨다운 (예약)
    skip_if_shorter_than: int = 0  # 이보다 짧은 입력은 사고 생략(지연/비용 완화)
    recall_limit: int = 5  # 사고 시 회상할 기억 개수
    log_sinks: list[str] = Field(default_factory=lambda: ["ltm"])  # ltm | stm (복수 가능)
    composer: str = "default"  # default | interpretation_only — 메인 프롬프트 조립 전략


class ProactiveConfig(BaseSettings):
    """Proactive 설정 (Tier 1). 기본 on. ThoughtConfig.enabled가 선행 조건."""

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = True  # Dual-Channel(요청 시 filler+백그라운드) 마스터 스위치
    confidence_threshold: float = 0.6  # daemon 발화 게이팅 임계치
    cooldown_sec: int = 300  # 세션별 proactive 발화 쿨다운
    daemon_enabled: bool = False  # B3 백그라운드 성찰 루프 (후속)
    daemon_interval_sec: int = 900  # 성찰 주기(초)


class VoiceConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    stt_provider: str = "browser"    # browser | whisper
    tts_provider: str = "browser"    # browser | supertonic
    whisper_model_size: str = "base"
    supertonic_model: str = "Supertone/supertonic-3"
    tts_lang: str = "ko"
    stt_lang: str = "ko-KR"
    tui_enabled: bool = False        # TUI 음성 입출력 활성화 (whisper/supertonic + 시스템 오디오 도구 필요)
    tui_record_seconds: float = 5.0  # TUI 음성 입력(Ctrl+R) 녹음 길이(초)


class JarvisSettings(BaseSettings):
    """
    최상위 설정 — .env 또는 환경변수에서 자동 로딩.
    중첩 오버라이드: JARVIS__LLM__API_KEY=...
    """

    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    plugin: PluginConfig = Field(default_factory=PluginConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    agents: AgentConfig = Field(default_factory=AgentConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    thought: ThoughtConfig = Field(default_factory=ThoughtConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    debug: bool = False
    log_level: str = "INFO"


_settings: JarvisSettings | None = None


def get_settings() -> JarvisSettings:
    global _settings
    if _settings is None:
        _settings = JarvisSettings()
    return _settings


def reset_settings() -> None:
    """테스트에서 설정을 초기화할 때 사용."""
    global _settings
    _settings = None
