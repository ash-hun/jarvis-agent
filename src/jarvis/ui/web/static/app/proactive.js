// 🔔 먼저 건넨 말에 대한 피드백 — 버튼 대신 다음 짧은 답(음성·텍스트)을 수락/무시로 읽는다 (C3).
import { send } from './ws.js';
import { appendMsg } from './messages.js';

// ponytail: 완전 일치 키워드만 본다. 자유 문장("응 그걸로 해줘")을 피드백으로 읽으려면 서버 분류가 필요하다
const ACCEPT = ['좋아', '좋아요', '고마워', '고마워요', '응', '네', '예', '그래', '확인', '오케이', '도움됨', '도움돼', '도움이 됐어'];
const DISMISS = ['아니', '아니요', '아니야', '됐어', '무시', '괜찮아', '괜찮아요', '나중에', '필요없어', '싫어'];
const QUESTION = '이 제안이 도움이 됐나요? 네 / 아니오 로 답해 주세요.';

let _pendingId = null;  // 피드백 대기 중인 proactive 메시지 id

function closeAsk() {
  _pendingId = null;
  document.querySelectorAll('.proactive-ask:not(.done)').forEach((el) => el.classList.add('done'));
}

// 🔔 메시지 아래에 질문을 붙이고 다음 답을 기다린다.
export function askFeedback(msgDiv, messageId) {
  _pendingId = messageId;
  const ask = document.createElement('div');
  ask.className = 'proactive-ask';
  ask.textContent = QUESTION;
  msgDiv.querySelector('.body').appendChild(ask);
}

// 짧은 답을 피드백으로 처리했으면 true. 아니면 보통 메시지로 흘려보낸다.
export function tryProactiveFeedback(text) {
  if (!_pendingId) return false;
  const t = text.trim().replace(/[.!?…~ㅋㅎ]/g, '').trim();
  const accepted = ACCEPT.includes(t);
  if (!accepted && !DISMISS.includes(t)) {
    closeAsk();  // 다른 얘기로 넘어갔다. 묻지 않은 걸로 둔다
    return false;
  }
  send({ type: 'proactive_feedback', id: _pendingId, accepted });
  closeAsk();
  appendMsg('SYS', 'sys', accepted ? '피드백: 도움됨' : '피드백: 무시');
  return true;
}
