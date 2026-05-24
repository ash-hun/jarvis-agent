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


class VoiceConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    stt_provider: str = "browser"    # browser | whisper
    tts_provider: str = "browser"    # browser | supertonic
    whisper_model_size: str = "base"
    supertonic_model: str = "Supertone/supertonic-3"
    tts_lang: str = "ko"
    stt_lang: str = "ko-KR"


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
