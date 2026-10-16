---
sidebar_position: 3
title: 전체 용어집
---

# 전체 용어집

서비스에서 사용하는 표기를 한눈에 정리한다. 특정 표기의 경우 표현기호도 함께 첨부한다.

| 이름 | 화면 기호 | 뜻 | 자세히 |
|---|---|---|---|
| 내적 사고 | 💭 | JARVIS 가 메인 응답과 따로 LLM 을 한 번 더 불러 판단을 만드는 일. 요청마다 한 번, 성찰 때 한 번 돈다 | [내적 사고](../concepts/architecture/inner-thought.md) |
| 사고 프레임 | | 내적 사고 한 번의 결과. 해석, 결정, 확신도, 먼저 할 말, 약속을 담은 구조화된 판단(`ThoughtFrame`) | [내적 사고 → 사고 프레임](../concepts/architecture/inner-thought.md#사고-프레임) |
| 사고 모델 | | 내적 사고에 쓰는 LLM. 메인 모델과 따로 작은 모델을 둘 수 있다 | [서비스 설정 값](./configuration.md) |
| Dual channel | 💬 | 오래 걸릴 요청이면 짧은 말을 먼저 하고 메인 응답은 뒤에서 처리하는 방식 | [먼저 행동하기 → Dual channel](../concepts/architecture/proactive.md#dual-channel) |
| filler | 💬 | Dual channel 에서 먼저 하는 짧은 말. "잠깐만요, 확인할게요" 같은 것 | [먼저 행동하기 → Dual channel](../concepts/architecture/proactive.md#dual-channel) |
| 성찰 | | 요청이 없는 시간에 주기적으로 도는 내적 사고. 먼저 말할 거리가 있는지 본다 | [먼저 행동하기](../concepts/architecture/proactive.md) |
| 먼저 건네는 말 | 🔔 | 성찰 끝에 가치가 분명할 때만 JARVIS 가 먼저 보내는 말 | [먼저 행동하기](../concepts/architecture/proactive.md) |
| 피드백 학습 | | 먼저 건네는 말에 대한 수락, 무시, 무응답으로 다음 발화 기준(임계치)을 움직이는 일 | [먼저 행동하기 → 피드백 학습](../concepts/architecture/proactive.md#피드백-학습) |
| 약속 (open loop) | | 대화에서 흘린 약속이나 끝내지 못한 일. 끝나거나 거두거나 기한이 지나면 닫힌다 | [Open Loop](../concepts/conversation/open-loop.md) |
| 스케줄 | | 정한 시각이나 주기에 도는 알림(reminder)이나 작업(task) | [Open Loop → 스케줄](../concepts/conversation/scheduling.md) |
| 외부 이벤트 | | MCP 도구를 주기적으로 불러 얻은 새 항목. 성찰의 재료가 된다 | [Open Loop → 외부 이벤트](../concepts/conversation/mcp.md) |
| 승인 | | 위험할 수 있는 도구를 실행하기 전에 사람에게 묻는 일 | [Tool & Approve system](../concepts/conversation/tools-and-approval.md) |
| 승인 기억 | | 승인 화면의 `ALWAYS` 로 남긴 명령 패턴. 다음부터 같은 패턴은 묻지 않는다 | [Tool & Approve system → 승인 기억](../concepts/conversation/tools-and-approval.md#승인-기억) |
| 절차 학습 | | 여러 도구로 성공한 작업을 다시 쓸 수 있는 절차 도구로 남기는 일 | [Tool & Approve system → 절차 학습](../concepts/conversation/tools-and-approval.md#절차-학습) |
| 작업 패턴 | | 사용자가 알려 준 일하는 방식. 에이전트마다 따로 기억한다 | [Memory Management → 작업 패턴](../concepts/memory.md#작업-패턴) |
| 사용자 모델 | | 기억에서 뽑은 사용자 성향. 모든 에이전트가 같이 읽는다 | [Open Loop → 사용자 모델과 저널](../concepts/memory.md#사용자-모델과-저널) |
| 세션 | | 대화 한 줄기. 만들 때 에이전트가 정해지고 바뀌지 않는다 | [Sessions](../concepts/conversation/sessions.md) |
| 최상위 에이전트 | | JARVIS 와 같은 층에서 자기 세션, 기억, 승인 규칙, 색을 가진 에이전트. KAREN 이 그 예다 | [에이전트 팀](../concepts/multi-agent-orchestration/index.md) |
| 서브 에이전트 | | 부모 턴 안에서 잠깐 도는 도구 같은 에이전트. 최상위 에이전트와 다르다 | [Orchestration Pattern](../concepts/multi-agent-orchestration/orchestration-pattern.md) |
| HUD | | 브라우저 화면(Web HUD). 리액터 구체를 가운데 두고 카드를 두른다 | [Web HUD 사용가이드](../start/web-hud.md) |
