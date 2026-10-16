"""[config] JarvisSettings: env 와 .env 에서 읽는 전체 설정 모델."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerConfig(BaseModel):
    """MCP 서버 연결 설정."""

    name: str
    transport: Literal["stdio", "http"] = "stdio"
    command: list[str] = Field(default_factory=list)  # stdio transport용 명령
    url: str | None = None  # http/sse transport용 엔드포인트
    env: dict[str, Any] = Field(default_factory=dict)  # MCP 서버 환경 변수. 값 타입을 좁히면 기존 설정 검증이 깨진다
    timeout: float = 30.0  # 연결/툴 호출 타임아웃(초) — 응답 없는 서버가 startup을 막지 않도록
    headers: dict[str, str] = Field(default_factory=dict)  # http transport용 커스텀 헤더
    auth_token: SecretStr | None = None  # http transport용 Bearer 토큰 (Authorization 헤더로 변환)


class WebSearchConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    brave_api_key: SecretStr | None = None  # 미설정 시 DuckDuckGo fallback


class LLMProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5"
    api_key: SecretStr | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0


class ApiUser(BaseModel):
    """Web HUD 접근 키 하나에 대응하는 사용자. 키 자체가 식별자이자 비밀값이다."""

    name: str
    roles: list[str] = Field(default_factory=lambda: ["user"])


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    require_auth: bool = True
    # Web HUD 접근 키 → 사용자. 비어 있으면 web 인증을 끈다(로컬 단독 사용). TUI 는 항상 NoAuth.
    # 예: JARVIS_SECURITY__API_KEYS='{"<random-key>": {"name": "jh", "roles": ["admin"]}}'
    api_keys: dict[str, ApiUser] = Field(default_factory=dict)
    allowed_roles: list[str] = Field(default_factory=lambda: ["user", "admin"])
    dangerous_commands: list[str] = Field(
        default_factory=lambda: ["rm -rf", "sudo", "curl | bash", "wget | bash", "> /dev/sda"]
    )
    require_approval_for: list[str] = Field(default_factory=lambda: ["bash", "write_file", "edit_file"])
    input_max_length: int = 10_000
    # 공용 승인 규칙. 모든 에이전트가 읽고, 사람이 직접 고친다
    approvals_path: str = "~/.jarvis/approvals.yaml"
    # 에이전트별 승인 규칙(<agent_id>.yaml). 승인 화면에서 "항상 허용"을 고르면 그 에이전트 파일에 쌓인다
    agent_approvals_dir: str = "~/.jarvis/approvals"


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    backend: Literal["in_memory", "postgres"] = "postgres"
    postgres_dsn: str | None = None  # None이면 session.postgres_dsn fallback
    window_size: int = 50
    compaction_threshold: int = 100_000
    fixed_facts: int = 3  # 매 턴 항상 넣는 상위 의미 사실 수(고정 블록)
    recall_limit: int = 3  # 질의로 회상해 넣는 항목 수(회상 블록)
    importance_threshold: float = 0.5  # 의미 추출 결과 중 이 값 미만은 버린다
    recency_half_life_hours: float = 168.0  # 검색 점수의 recency 반감기(일주일)
    importance_half_life_days: float = 90.0  # 되뇌기 없는 항목의 importance 반감기. 0 이면 감쇠 없음
    interference_threshold: float = 0.6  # 주제가 다른데 이보다 비슷한 의미 항목 쌍은 간섭 후보로 표시
    consolidate_on_idle: bool = True  # 사용자가 조용할 때(daemon idle 틱) 요약에서 사실을 추출한다
    # 의미 유사도 검색. provider 를 비우면 키워드 검색만 한다. Postgres 는 pgvector 확장이 필요하다
    embedding_provider: str = ""  # "" | openai | ollama | vllm
    embedding_model: str = ""  # 비우면 provider 기본값 (openai: text-embedding-3-small, ollama: nomic-embed-text)
    embedding_dimensions: int = 0  # 비우면 provider 기본값. vllm 은 필수
    embedding_api_key: SecretStr | None = None  # 비우면 llm.api_key
    embedding_base_url: str | None = None  # 비우면 provider 기본값
    min_similarity: float = 0.3  # 이 코사인 미만은 의미 검색 후보에서 제외


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    persistence_backend: Literal["jsonl", "postgres"] = "jsonl"
    sessions_dir: str = "~/.jarvis/sessions"
    postgres_dsn: str | None = None


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["tui", "web"] = "tui"
    theme: str = "dark"
    show_thinking: bool = True


HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class BrandPalette(BaseModel):
    """에이전트 색감. 나머지 톤(밝은/어두운 변형, 반투명 선)은 UI가 여기서 유도한다."""

    primary: HexColor = "#5fc8e2"  # 선·링·텍스트 강조의 주색
    accent: HexColor = "#f0b35f"  # 경고·인디케이터 보조색
    background: HexColor = "#02060c"  # 화면 바탕
    nebula: list[HexColor] = Field(  # 리액터 코어 성운 입자 색 (안쪽 → 바깥)
        default_factory=lambda: ["#3a5bff", "#8a4dff", "#ff6ad5"]
    )


class BrandConfig(BaseModel):
    """에이전트 정체성 — 워드마크·명언·색감. 에이전트마다 다르게 둔다.

    지금은 env(JARVIS_BRAND__*)로 한 에이전트분을 읽는다. 한 서버에 여러 에이전트를
    띄우게 되면 에이전트별 파일에서 이 모델을 채우는 로더만 추가하면 된다.
    """

    model_config = ConfigDict(extra="ignore")

    name: str = "J.A.R.V.I.S."
    quote: str = "Proof the Heart"
    palette: BrandPalette = Field(default_factory=BrandPalette)


class PluginConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    plugins_dir: str = "~/.jarvis/plugins"
    skills_dir: str = "~/.jarvis/skills"
    tools_dir: str = "~/.jarvis/tools"
    watch_files: bool = True


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    schedules_dir: str = "~/.jarvis/schedules"


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    agents_dir: str = "~/.jarvis/agents"
    # supervisor 패턴의 감독자 system_prompt. 비우면 기본 문구. 파일 경로면 그 내용을 읽는다
    supervisor_prompt: str = ""


class TeamConfig(BaseModel):
    """최상위 에이전트(JARVIS 와 같은 층) 정의 디렉터리. 파일 하나가 에이전트 하나이고 파일 이름이 id 다.

    서브 에이전트(agents_dir)와 다르다. 여기 에이전트는 자기 세션, 기억, 약속, 승인 규칙을 가진다.
    """

    model_config = ConfigDict(extra="ignore")

    dir: str = "~/.jarvis/team"


class ThoughtConfig(BaseModel):
    """Inner Thought Engine 설정 (Tier 0). 기본 on — JARVIS_THOUGHT__ENABLED=false로 끈다."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    model: str = ""  # 비우면 메인 LLM 모델, 지정 시 별도 모델
    # 사고 모델을 메인과 완전 분리 (예: 메인=anthropic, 사고=ollama 로컬).
    # 비우면 메인 LLM의 provider/key/base_url을 그대로 상속.
    provider: str = ""
    api_key: SecretStr | None = None
    base_url: str = ""
    prompt_path: str = "~/.jarvis/inner_thought.md"
    reflection_prompt_path: str = "~/.jarvis/inner_thought_reflection.md"  # daemon 성찰용
    confidence_threshold: float = 0.6  # Tier 1 게이팅용 (Tier 0은 기록만)
    proactive_cooldown_sec: int = 300  # Tier 1 발화 쿨다운 (예약)
    skip_if_shorter_than: int = 0  # 이보다 짧은 입력은 사고 생략(지연/비용 완화)
    recall_limit: int = 5  # 사고 시 회상할 기억 개수
    # 요청 사고 시점. before: 사고 뒤 응답(해석이 이번 응답에 섞임). race: wait_sec 까지만 기다림.
    # after: 응답 뒤 사고. 사고와 메인이 같은 GPU 면 after 가 가장 빠르다. race, after 의 늦은 사고는 기록만 남긴다
    request_timing: Literal["before", "race", "after"] = "race"
    wait_sec: float = 3.0  # race 에서 기다리는 상한
    history_turns: int = 8  # 사고 프롬프트에 넣는 최근 대화 턴 수
    history_chars: int = 240  # 턴당 글자 수 상한
    log_sinks: list[str] = Field(default_factory=lambda: ["ltm"])  # ltm | stm (복수 가능)
    composer: str = "default"  # default | interpretation_only — 메인 프롬프트 조립 전략


class OpenLoopConfig(BaseModel):
    """Open-loop 추적 영속화 설정 (Tier 2)."""

    model_config = ConfigDict(extra="ignore")

    backend: Literal["jsonl", "in_memory", "postgres"] = "jsonl"
    path: str = "~/.jarvis/openloops.jsonl"  # jsonl 백엔드 경로
    postgres_dsn: str | None = None  # None이면 session/memory DSN fallback
    expire_after_sec: int = 21_600  # 기한이 이만큼 지나면 expired 로 닫는다(6시간)
    max_age_sec: int = 604_800  # 기한 없는 약속의 수명(7일). 0 이면 기한 없는 약속은 닫지 않는다


class UserModelConfig(BaseModel):
    """User Model 설정 (Tier 3 D1). ThoughtConfig.enabled가 선행 조건."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    backend: Literal["jsonl", "in_memory"] = "jsonl"
    path: str = "~/.jarvis/user_model.json"
    build_source_limit: int = 30  # /usermodel build 시 증류에 쓸 최근 기억 개수


class ProactiveConfig(BaseModel):
    """Proactive 설정 (Tier 1). 기본 on. ThoughtConfig.enabled가 선행 조건."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True  # Dual-Channel(요청 시 filler+백그라운드) 마스터 스위치
    confidence_threshold: float = 0.6  # daemon 발화 게이팅 임계치
    cooldown_sec: int = 300  # 세션별 proactive 발화 쿨다운
    # 🔔 뒤 답이 없으면 다시 말하지 않는다. 이만큼 답이 없으면 그 발화를 한 번 약한 무시로 학습
    ignore_after_sec: int = 600
    daemon_enabled: bool = True  # B3 백그라운드 성찰 루프 (기본 on, false로 끔)
    daemon_interval_sec: int = 120  # 성찰 주기(초) — interval 트리거용. 로컬과 배포 모두 이 값
    # 성찰 트리거: interval(주기) | idle(조용해지면) | both(둘 중 먼저)
    daemon_trigger: Literal["interval", "idle", "both"] = "interval"
    daemon_idle_sec: int = 180  # idle 트리거 — 이만큼 조용하면 1회 성찰


class ExternalTriggerConfig(BaseModel):
    """외부 트리거 설정 (Proactive Phase 3). 소스 YAML이 없으면 전 구간 no-op."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    sources_dir: str = "~/.jarvis/external_sources"
    seen_backend: Literal["jsonl", "in_memory"] = "jsonl"
    seen_path: str = "~/.jarvis/external_seen.jsonl"
    seen_ttl_sec: int = 604_800  # 7일 — dedup 키 보관 기간
    seen_max_keys: int = 10_000  # dedup 스토어 상한(무한 증식 방지)
    max_events_per_tick: int = 20  # 한 번의 성찰에 실을 이벤트 상한
    inbox_max_events: int = 200  # inbox 상한 — 초과분은 드롭 건수를 로그로 노출
    detail_max_chars: int = 500  # 프라이버시·토큰 상한(원문 절단)
    store_detail_in_log: bool = False  # 사고 로그(LTM)에 원문 detail 저장 여부


class ProcedureConfig(BaseModel):
    """절차 학습. 도구를 여러 번 써서 성공한 작업을 세션 종료 때 절차 초안으로 남기고, 승인하면 도구가 된다."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    dir: str = "~/.jarvis/procedures"
    min_tool_calls: int = 3  # 이보다 적게 도구를 쓴 작업은 절차로 볼 가치가 없다


class NotifyConfig(BaseModel):
    """외부 알림 채널. 열린 UI 가 없어도 스케줄 결과와 proactive 발화가 닿는 곳."""

    model_config = ConfigDict(extra="ignore")

    slack_webhook_url: SecretStr | None = None  # 비우면 외부 알림 없음
    kinds: list[str] = Field(default_factory=lambda: ["reminder", "proactive"])  # reminder | proactive


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stt_provider: str = "browser"    # browser | whisper
    tts_provider: str = "browser"    # browser | supertonic
    whisper_model_size: str = "base"
    supertonic_model: str = "Supertone/supertonic-3"
    tts_lang: str = "ko"
    english_tts_provider: str = ""   # 비우면 영어 문장도 tts_provider 가 읽는다. piper
    piper_model: str = "~/.jarvis/voices/en-voice.onnx"  # 같은 자리에 .onnx.json 이 있어야 한다
    piper_noise_scale: float = 0.4   # 낮을수록 음정 떨림이 줄고 말투가 단조로워진다. Piper 기본은 0.667
    stt_lang: str = "ko-KR"
    tui_enabled: bool = False        # TUI 음성 입출력 활성화 (whisper/supertonic + 시스템 오디오 도구 필요)
    tui_record_seconds: float = 5.0  # TUI 음성 입력(Ctrl+R) 녹음 길이(초)

    def english_tts_options(self) -> dict[str, object]:
        """english_tts_provider 팩토리에 넘길 생성 옵션."""
        if self.english_tts_provider != "piper":
            return {}
        return {"model_path": self.piper_model, "noise_scale": self.piper_noise_scale}


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
    brand: BrandConfig = Field(default_factory=BrandConfig)
    plugin: PluginConfig = Field(default_factory=PluginConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    agents: AgentConfig = Field(default_factory=AgentConfig)
    team: TeamConfig = Field(default_factory=TeamConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    thought: ThoughtConfig = Field(default_factory=ThoughtConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    openloop: OpenLoopConfig = Field(default_factory=OpenLoopConfig)
    user_model: UserModelConfig = Field(default_factory=UserModelConfig)
    external: ExternalTriggerConfig = Field(default_factory=ExternalTriggerConfig)
    procedures: ProcedureConfig = Field(default_factory=ProcedureConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
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
