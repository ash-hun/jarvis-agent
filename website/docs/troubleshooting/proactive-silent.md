---
sidebar_position: 1
title: 먼저 건네는 말이 오지 않을 때
---

# 먼저 건네는 말이 오지 않을 때

요청이 없는 시간에 JARVIS 가 🔔 먼저 건네는 말을 보내지 않는다. 대부분은 말할 근거가 없어 침묵한 정상 동작이고, JARVIS 는 먼저 말하지 않을 때마다 그 이유를 백엔드 로그에 남기므로 로그 한 줄로 원인을 가를 수 있다.

## 확인 순서

1. 백엔드 로그에서 `[Thought] proactive silent:` 나 `[Proactive] suppressed` 로 시작하는 줄을 찾는다. Docker 라면 `docker compose logs jarvis-backend` 로 본다.
2. 줄이 있으면 아래 [원인과 해결](#원인과-해결)에서 같은 문구를 찾는다. 정상 동작인지, 설정이나 모델을 봐야 하는지가 나뉜다.
3. 로그가 아예 없으면 daemon 설정(`JARVIS_PROACTIVE__DAEMON_ENABLED`)과 [사고 프레임](./thought-frame.md) 오류를 본다.

찾을 로그는 다음과 같다.

```text
[Thought] proactive silent: cooldown
[Thought] proactive silent: confidence 0.72 < 0.85
[Thought] proactive silent: empty utterance
[Thought] proactive silent: decision=silent
[Thought] proactive silent: awaiting reply
[Thought] proactive silent: nothing to tell
[Thought] proactive silent: repeats a recent proactive message
[Thought] proactive silent: repeats the last answer
[Thought] proactive silent: decision tev1 p=0.12 < floor 0.30
[Thought] proactive silent: anchor missing (<문장>)
[Proactive] suppressed while answering: <문장>
```

## 원인과 해결

### 정상 동작인 경우

아래 로그는 JARVIS 가 일부러 침묵한 것이다. 고칠 것은 없고, 조건이 바뀌면 다시 말한다.

- `decision=<값>`: 사고가 `act`, `ask` 가 아닌 결정(`silent` 등)을 냈다. 지금 말할 일이 없다고 판단한 것이다
- `awaiting reply`: 직전 🔔 에 아직 답이 없다. 사용자가 메시지나 피드백을 보내면 다시 말할 수 있다. 600초 동안 답이 없으면 그 발화를 한 번 무시로 학습한다
- `cooldown`: 마지막 발화 뒤 300초가 지나지 않았다
- `nothing to tell`: 챙길 약속(기한이 없거나 기한이 30분 안으로 다가왔거나 지난 약속)도 새 외부 이벤트도 없어 사고 모델을 부르지 않았다. 먼저 말할 근거가 없는 것이다. 대화나 약속, 이벤트가 그대로면 로그 없이 건너뛴다(`unchanged`). 새로 연 세션에 아직 대화가 없을 때도 로그 없이 건너뛴다
- `repeats a recent proactive message`, `repeats the last answer`: 사고가 최근 🔔 세 개 중 하나나 10분 안에 한 마지막 답과 같은 내용을 다시 골랐다
- `decision <모델> p=… < floor 0.30`: decision model(`JARVIS_PROACTIVE__DECISION_MODEL`)을 쓸 때만 나온다. decision model 이 지금 말할 확률을 0.3 보다 낮게 봐서 사고 모델을 부르지 않았다. `items=0.62,0.08` 처럼 항목별 확률이 붙어 있으면, 전체 확률과 가장 높은 항목 확률 중 작은 쪽이 0.3 보다 낮았던 것이다. 바로 다음 줄에 `decision=silent` 가 함께 남는다
- `[Proactive] suppressed while answering`: 세션이 답하는 중에 🔔 가 생겼다. 답과 섞이지 않게 버린 것이다. 버린 🔔 는 쿨다운, 응답 대기, 무시 학습에 들어가지 않고 뒤이어 `proactive silent: suppressed` 가 남는다
- `[Proactive] suppressed during turn hook`: 그 세션이 Focus 작업 중이다. Focus 동안에는 🔔 를 보내지 않는다(💬 filler 와 맡긴 일의 답은 보낸다). `/focus stop` 으로 끝내면 다시 나온다

### 설정이나 모델을 봐야 하는 경우

- `confidence`: 사고 프레임의 확신도가 임계치보다 낮다. Process Pattern Analysis 로 임계치가 올라갔을 수도 있다
- `empty utterance`: 모델이 건넬 말을 채우지 않았다. 사고 템플릿에 `utterance` 키가 있는지 확인한다
- `anchor missing (<문장>)`: decision model 을 쓸 때만 나온다. 건넬 말이 근거 항목(확률이 가장 높은 약속이나 이벤트)의 숫자, 이름, 핵심 낱말을 하나도 담지 않아 막았다. 괄호 안 문장이 인사나 사용자 분석문이면 맞게 막은 것이다. 근거를 다른 말로 바꿔 쓴 알림("카드값 128만원")이 자주 막히면 사고 모델이 [먼저 꺼낼 항목]을 인용하는지 사고 템플릿을 확인한다. 바로 다음 줄에 `decision=silent` 가 함께 남는다
- 로그가 아예 없음: daemon 이 꺼져 있거나(`JARVIS_PROACTIVE__DAEMON_ENABLED`) 성찰 프레임이 깨지고 있는 것이다

관련 문서: [Proactive Dialogue](../concepts/conversation/proactive.md), [피드백 학습](../concepts/conversation/proactive.md#피드백-학습)
