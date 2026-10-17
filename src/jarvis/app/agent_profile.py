"""[app] AgentProfile: 에이전트 한 명분의 정체성, 모델, 사고와 proactive 설정, 피드백 학습기."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.agent_layer.thought.reply import ReplyClassifier
    from jarvis.config import BrandConfig, JarvisSettings, ProactiveConfig, ThoughtConfig
    from jarvis.core.proactive.core import EmitProactive, ProactivityCore
    from jarvis.core.proactive.feedback import FeedbackLearner
    from jarvis.model_layer.types import ModelConfig

# 지금은 에이전트가 하나다. 기존 메모리와 세션 데이터가 이 id 로 쌓여 있으므로 바꾸지 않는다
MAIN_AGENT_ID = "main"

ProactivityFactory = Callable[["EmitProactive"], "ProactivityCore"]


@dataclass(frozen=True)
class AgentProfile:
    """에이전트마다 달라질 수 있는 것을 한곳에 모은다. 세션 조립은 이 묶음만 보고 에이전트를 만든다."""

    agent_id: str
    brand: "BrandConfig"
    model: "ModelConfig"
    thought: "ThoughtConfig"
    proactive: "ProactiveConfig"
    feedback_learner: "FeedbackLearner"
    # 아래 셋은 정의 파일에서 온다. main 은 비워 둬서 기존 동작(기본 시스템 프롬프트, 도구 전체)을 지킨다
    description: str = ""
    system_prompt: str | None = None
    tools: tuple[str, ...] = ()

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
