// 키워드로 판정이 안 되는 짧은 답을 서버의 사고 모델 분류기에 묻는다. 🔔 피드백과 Full-voice 승인 답이 쓴다.
import { send } from './ws.js';

// 서버는 6초 안에 답을 준다. 그보다 늦으면 연결 문제로 보고 fallback 으로 간다
const REPLY_TIMEOUT_MS = 8000;
const FALLBACK = { feedback: 'other', approval: 'unclear' };

let _enabled = false;          // connected.reply_classifier — 사고가 꺼져 있으면 묻지 않는다
const _waiting = new Map();    // `${kind}:${id}` → resolve

export function setReplyClassifier(on) { _enabled = !!on; }
export function replyClassifierOn() { return _enabled; }

// verdict 하나를 돌려준다. 같은 답을 기다리는 중에 다시 부르면 먼저 것을 fallback 으로 끝낸다.
export function classifyReply(kind, id, text, context = '', hasAlways = false) {
  if (!_enabled) return Promise.resolve(FALLBACK[kind]);
  const key = `${kind}:${id}`;
  _waiting.get(key)?.(FALLBACK[kind]);
  return new Promise((resolve) => {
    const timer = setTimeout(() => finish(key, FALLBACK[kind]), REPLY_TIMEOUT_MS);
    _waiting.set(key, (verdict) => { clearTimeout(timer); resolve(verdict); });
    send({ type: 'reply_classify', kind, id, text, context, has_always: hasAlways });
  });
}

function finish(key, verdict) {
  const resolve = _waiting.get(key);
  if (!resolve) return;
  _waiting.delete(key);
  resolve(verdict);
}

// events.js 가 reply_classified 를 넘긴다. 기다리는 게 없으면(시간 초과 뒤 도착) 버린다.
export function onReplyClassified(msg) {
  finish(`${msg.kind}:${msg.id}`, msg.verdict || FALLBACK[msg.kind] || 'other');
}
