"""[app] AgentProfile: 에이전트 한 명분의 정체성, 모델, 사고와 proactive 설정, 피드백 학습기."""

from typing import TYPE_CHECKING
from dataclasses import dataclass
from collections.abc import Callable

if TYPE_CHECKING:
    from jarvis.config import BrandConfig, JarvisSettings, ProactiveConfig, ThoughtConfig
    from jarvis.core.proactive.core import EmitProactive, ProactivityCore
    from jarvis.agent_layer.thought.reply import ReplyClassifier
    from jarvis.core.proactive.feedback import FeedbackLearner
    from jarvis.model_layer.types import ModelConfig

# 지금은 에이전트가 하나다. 기존 메모리와 세션 데이터가 이 id 로 쌓여 있으므로 바꾸지 않는다
MAIN_AGENT_ID = "main"

# 개성과 상관없이 모든 에이전트가 지킨다. 업무 지시보다 뒤에 둬서 마지막으로 읽히게 한다
ANSWER_RULE = (
    "답은 간결하게 한다. 지시받은 것에 필요한 말만 하고, 묻지 않은 설명, 일반론, 대안, 부연은 붙이지 않는다."
)

ProactivityFactory = Callable[["EmitProactive"], "ProactivityCore"]


def compose_system_prompt(persona: str, instructions: str | None) -> str:
    """개성(말투), 업무 지시, 모든 에이전트 공통 답변 규칙 순으로 잇는다."""
    parts = [p.strip() for p in (persona, instructions or "", ANSWER_RULE) if p and p.strip()]
    return "\n\n".join(parts)


@dataclass(frozen=True)
class AgentProfile:
    """에이전트마다 달라질 수 있는 것을 한곳에 모은다. 세션 조립은 이 묶음만 보고 에이전트를 만든다."""

    agent_id: str
    brand: "BrandConfig"
    model: "ModelConfig"
    thought: "ThoughtConfig"
    proactive: "ProactiveConfig"
    feedback_learner: "FeedbackLearner"
    # 아래 셋은 정의 파일에서 온다. main 은 개성만 시스템 프롬프트로 두고 도구는 전체를 쓴다
    description: str = ""
    system_prompt: str | None = None
    tools: tuple[str, ...] = ()
    # 경계. ask 는 스스로 할 때(목표 차례, 스케줄 작업, 먼저 해 두기) 하지 않고 물어야 하는 도구,
    # never 는 어디서도 쓰지 않는 도구. 사용자가 대화로 직접 시킨 일은 이미 물은 것으로 본다
    ask_tools: tuple[str, ...] = ()
    never_tools: tuple[str, ...] = ()

    @property
    def is_main(self) -> bool:
        return self.agent_id == MAIN_AGENT_ID

    @property
    def name(self) -> str:
        """화면과 다른 에이전트가 부르는 이름. 브랜드 워드마크와 같다."""
        return self.brand.name

    @classmethod
    def main(
        cls, settings: "JarvisSettings", model: "ModelConfig", feedback_learner: "FeedbackLearner"
    ) -> "AgentProfile":
        """env 설정에서 기본 에이전트(main)를 만든다."""
        return cls(
            agent_id=MAIN_AGENT_ID,
            brand=settings.brand,
            model=model,
            thought=settings.thought,
            proactive=settings.proactive,
            feedback_learner=feedback_learner,
            system_prompt=compose_system_prompt(settings.brand.persona, None),
        )

    def thought_model(self) -> "ModelConfig":
        """사고 모델: 사고 설정에 지정한 항목만 메인 모델에서 바꾸고 나머지는 이어받는다."""
        from jarvis.model_layer.types import ModelConfig

        tcfg = self.thought
        api_key = tcfg.api_key.get_secret_value() if tcfg.api_key is not None else self.model.api_key
        return ModelConfig(
            provider=tcfg.provider or self.model.provider,
            model=tcfg.model or self.model.model,
            api_key=api_key,
            base_url=tcfg.base_url or self.model.base_url,
            temperature=self.model.temperature,
            max_tokens=self.model.max_tokens,
        )

    def reply_classifier(self) -> "ReplyClassifier | None":
        """🔔 짧은 답과 음성 승인 답 분류기. 사고가 꺼져 있으면 None(화면은 키워드만 쓴다)."""
        if not self.thought.enabled:
            return None
        from jarvis.agent_layer.thought.reply import ReplyClassifier

        return ReplyClassifier(self.thought_model())

    def proactivity_factory(self) -> "ProactivityFactory | None":
        """proactive 와 사고가 둘 다 켜져 있을 때만, 세션의 emit 에 묶을 ProactivityCore 팩토리."""
        pcfg = self.proactive
        # 사고가 꺼져 있으면 프레임이 없어 proactivity 가 무의미하다
        if not pcfg.enabled or not self.thought.enabled:
            return None
        from jarvis.core.proactive import DefaultProactivityCore, DefaultProactivityPolicy

        learner = self.feedback_learner

        def factory(emit: "EmitProactive") -> "ProactivityCore":
            policy = DefaultProactivityPolicy(
                confidence_threshold=pcfg.effective_threshold(),
                cooldown_sec=pcfg.cooldown_sec,
                ignore_after_sec=pcfg.ignore_after_sec,
                threshold_provider=learner.threshold,
            )
            return DefaultProactivityCore(emit_proactive=emit, policy=policy)

        return factory
