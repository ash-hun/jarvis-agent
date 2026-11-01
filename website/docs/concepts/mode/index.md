---
sidebar_position: 0
title: Mode
---

import InfoMode from '@site/src/figures/info-mode.svg';

# Mode

Web HUD 에서 에이전트와 일하는 방식을 상황에 맞게 바꾸는 모드전환 시스템을 소개한다. 모드는 말로 주고받는 방식을 정하는 음성 축과, 화면과 에이전트가 무엇에 집중할지를 정하는 작업 축으로 나뉜다. 두 축은 따로 고르고 겹쳐 쓸 수 있어서, Full-voice 로 Focus 작업을 하는 조합도 가능하다.

<figure className="info-fig">
  <InfoMode />
</figure>

## 서비스 기능

### Mode가 주목한 점

같은 사용자라도 상황마다 에이전트와 소통하고 싶은 방식이 다르다. 책상 앞에서는 답을 화면으로 읽는 편이 빠르고, 손이 바쁠 때는 말로 묻고 들어야 한다. 긴 작업 하나에 매달릴 때는 대화 목록보다 분석, 조사, 기록, 진행률이 한 화면에 보이는 편이 낫다. 기존의 Chatbot Assistant는 대개 음성 모드와 작업 화면을 하나의 스위치로 묶어 두기 때문에, "말로 하면서 작업에 집중" 하는 조합을 고를 수 없다. Jarvis-Agent는 이러한 부분에서 착안하여 음성과 작업을 서로 독립된 두 축으로 나누고, 사용자가 필요한 조합을 직접 고를 수 있도록 한다.

### 어떤 기능을 가지고 있나요?

| 축 | 모드 | 켜는 법 | 설명 |
|---|---|---|---|
| 음성 | Default | 헤더 `DEFAULT` | 응답은 화면으로 보고, 구체를 눌러 말로 한 요청만 읽어 준다. |
| 음성 | Full-voice | 헤더 `FULL-VOICE` | 응답, 승인 요청, 먼저 건네는 말까지 모두 말로 묻고 답한다. 자세한 동작은 [Voice Interface](../conversation/voice.md#full-voice) 에 있다. |
| 작업 | Focus | `/focus <작업>`, 음성 `포커스 모드 <작업>` | 작업 하나에 집중하도록 보조 에이전트를 붙이고 화면을 작업 중심으로 바꾼다. 자세한 동작은 [Focus Mode](./focus-mode.md) 에 있다. |

## 세부 구현

### 하위 페이지

| 페이지 | 다루는 것 |
|---|---|
| [Focus Mode](./focus-mode.md) | sub-agent 넷(분석, 조사, 기록, 진행), 턴 훅, 화면 네 영역, 기록 파일과 재시작 복구 |
| [Voice Interface → Full-voice](../conversation/voice.md#full-voice) | 응답, 승인 요청, 먼저 건네는 말을 읽고 답을 듣는 음성 루프 |

### 같이 쓸 때

- Focus 중에도 음성 모드는 헤더에서 그대로 바꾼다. 헤더의 `FOCUS` 표시는 음성 모드와 따로 붙는다
- 음성으로 시작한 요청이면 Default 에서도 승인을 음성으로 묻는다. Focus 중이어도 같다
- Focus 를 끝내도 음성 모드는 바뀌지 않는다

## Performance Experiments

하위 페이지에 있는 실험의 핵심 숫자를 한눈에 보기 쉽도록 모았다. 조건과 해석은 각 페이지에 있다.

| 실험 | 핵심 숫자 | 페이지 |
|---|---|---|
| Focus 첫 응답 시간 | `/focus` 부터 첫 응답까지 gemma4:e4b 19.47~20.08초, gpt-4o-mini 2.77~2.89초 | [Focus Mode](./focus-mode.md#첫-응답-시간과-조사-형식) |
| Focus 조사 형식 | 선례 3개 이하: gemma4:e4b 2/4, gpt-4o-mini 4/4. 번호 목록 없음: 두 모델 모두 4/4 | [Focus Mode](./focus-mode.md#첫-응답-시간과-조사-형식) |
| 음성 Focus 키워드 해석 | 종료 시도 2번: 고치기 전 모두 대화로 갔고, 고친 뒤 2번 모두 `/focus stop`. 시작 시도 3번은 고친 뒤에도 시작으로 잡히지 않았다 | [Voice Interface](../conversation/voice.md#실제-전사-기록에서-focus-키워드-해석) |
| 영어 답의 첫 소리 | 조각마다 받기 1.2~2.2초, 한 번에 합성 2.6~7.8초 | [Voice Interface](../conversation/voice.md#jarvis-답의-첫-소리까지-한-번에-문장마다-조각마다) |
