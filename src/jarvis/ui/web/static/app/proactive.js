// 🔔 먼저 건넨 말에 대한 피드백 — 버튼 대신 다음 짧은 답(음성·텍스트)을 수락/무시로 읽는다 (C3).
import { send } from './ws.js';
import { appendMsg } from './messages.js';
import { classifyReply, replyClassifierOn } from './reply.js';

// 완전 일치 키워드는 바로 처리하고, 그 밖의 짧은 답은 서버 분류기에 묻는다("응 그걸로 해줘")
const ACCEPT = ['좋아', '좋아요', '고마워', '고마워요', '응', '네', '예', '그래', '확인', '오케이', '도움됨', '도움돼', '도움이 됐어'];
const DISMISS = ['아니', '아니요', '아니야', '됐어', '무시', '괜찮아', '괜찮아요', '나중에', '필요없어', '싫어'];
const QUESTION = '이 제안이 도움이 됐나요? 네 / 아니오 로 답해 주세요.';
export const QUESTION_SPOKEN = '이 제안이 도움이 됐나요? 네 또는 아니오로 답해 주세요.';
// 이보다 긴 답은 새 요청으로 보고 분류하지 않는다. 짧은 답에만 1~2초 분류 지연을 쓴다
const CLASSIFY_MAX_CHARS = 40;

let _pendingId = null;   // 피드백 대기 중인 proactive 메시지 id
let _pendingText = '';   // 그 🔔 본문. 분류기가 무엇에 대한 답인지 보게 한다

function closeAsk() {
  _pendingId = null;
  document.querySelectorAll('.proactive-ask:not(.done)').forEach((el) => el.classList.add('done'));
}

export function isFeedbackPending() { return _pendingId !== null; }

// 🔔 메시지 아래에 질문을 붙이고 다음 답을 기다린다.
export function askFeedback(msgDiv, messageId) {
  _pendingId = messageId;
  _pendingText = msgDiv.querySelector('.body').textContent.trim();
  const ask = document.createElement('div');
  ask.className = 'proactive-ask';
  ask.textContent = QUESTION;
  msgDiv.querySelector('.body').appendChild(ask);
}

function showFeedback(accepted, how = '') {
  closeAsk();
  appendMsg('SYS', 'sys', `${accepted ? '피드백: 도움됨' : '피드백: 무시'}${how}`);
}

// 짧은 답을 피드백으로 처리했으면 true. 아니면 보통 메시지로 흘려보낸다(질문은 닫힌다).
export async function tryProactiveFeedback(text) {
  if (!_pendingId) return false;
  const id = _pendingId;
  const t = text.trim().replace(/[.!?…~ㅋㅎ]/g, '').trim();
  if (ACCEPT.includes(t) || DISMISS.includes(t)) {
    const accepted = ACCEPT.includes(t);
    send({ type: 'proactive_feedback', id, accepted });
    showFeedback(accepted);
    return true;
  }
  if (!replyClassifierOn() || t.length > CLASSIFY_MAX_CHARS) {
    closeAsk();  // 다른 얘기로 넘어갔다. 묻지 않은 걸로 둔다
    return false;
  }
  // 서버가 accept / dismiss 면 학습까지 하고 돌려준다. other 면 보통 메시지다
  const verdict = await classifyReply('feedback', id, text, _pendingText);
  if (_pendingId !== id) return verdict !== 'other';  // 기다리는 사이 새 🔔 가 왔다. 이 답은 옛 질문의 것
  if (verdict === 'accept' || verdict === 'dismiss') {
    showFeedback(verdict === 'accept', ' (분류)');
    return true;
  }
  closeAsk();
  return false;
}
