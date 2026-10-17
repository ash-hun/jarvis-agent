// 도구 실행 승인 모달 — ALLOW(이번 한 번) · ALWAYS(패턴을 규칙으로) · DENY.
import { send } from './ws.js';
import { classifyReply } from './reply.js';

const $overlay = document.getElementById('approval-overlay');
const $reason  = document.getElementById('approval-reason');
const $command = document.getElementById('approval-command');
const $hint    = document.getElementById('approval-hint');
const $allow   = document.getElementById('btn-allow');
const $deny    = document.getElementById('btn-deny');
const $always  = document.getElementById('btn-always');

// 음성 답 해석은 거부 쪽으로 기운다. 부정어가 섞이면 거부, 긍정 표현이 분명하면 허용.
// 키워드로 판정이 안 되면(unclear) 서버 분류기에 묻고, 분류기도 분명하지 않으면 거부.
const VOICE_DENY = ['거부', '거절', '아니', '안돼', '안되', '안해', '하지마', '하지말', '취소', '멈춰', '그만', 'no', 'deny', 'stop'];
const VOICE_ALWAYS = ['항상', '언제나', '앞으로도', 'always'];
const VOICE_ALLOW = ['허용', '허락', '승인', '실행해', '진행해', 'allow'];
const VOICE_YES = ['응', '네', '예', '그래', '좋아', '오케이', '해', '해줘', 'ok', 'okay', 'yes'];
const SPEECH_COMMAND_MAX = 120;
const HINT_CLICK = '이 명령을 허용하시겠습니까? (120초 후 자동 거부)';
const HINT_VOICE = '음성으로 답하세요: 허용, 거부 (120초 후 자동 거부)';
const HINT_VOICE_ALWAYS = '음성으로 답하세요: 허용, 항상, 거부 (120초 후 자동 거부)';
const HEARD_SPEECH = {
  allow:  '허용으로 들었습니다.',
  always: '항상 허용으로 들었습니다.',
  deny:   '거부로 들었습니다.',
};
let _currentCommand = '';

let _currentId = null;
let _alwaysPattern = null;

// voice 면 화면을 가리지 않는 아래쪽 띠로 띄운다. 묻고 답하기는 음성이 하고, 명령은 계속 보이게 둔다
export function showApproval(id, command, reason, alwaysPattern, { voice = false } = {}) {
  _currentId = id;
  _alwaysPattern = alwaysPattern || null;
  _currentCommand = command || '';
  $reason.textContent  = reason || '도구 실행 승인이 필요합니다.';
  $command.textContent = command;
  // 항상 허용: 서버가 제안한 패턴이 있을 때만. 규칙은 사용자가 이 버튼을 눌러야 생긴다.
  if (alwaysPattern) {
    $always.textContent = `ALWAYS · ${alwaysPattern}`;
    $always.title = `앞으로 "${alwaysPattern}" 은 묻지 않고 허용`;
    $always.classList.remove('hidden');
  } else {
    $always.classList.add('hidden');
  }
  $hint.textContent = voice ? (alwaysPattern ? HINT_VOICE_ALWAYS : HINT_VOICE) : HINT_CLICK;
  $overlay.classList.toggle('voice', voice);
  $overlay.classList.remove('hidden');
}

// 다른 창이 먼저 답했거나 시간이 지났다. 같은 요청을 보여주고 있을 때만 닫는다
export function closeApproval(id) {
  if (!_currentId || _currentId !== id) return false;
  $overlay.classList.add('hidden');
  _currentId = null;
  _alwaysPattern = null;
  return true;
}

export function isApprovalOpen() { return _currentId !== null; }

// 모달 내용을 읽어 줄 한 문장. 항상 허용은 서버가 패턴을 제안했을 때만 선택지에 넣는다.
export function approvalSpeech(command, alwaysPattern) {
  let cmd = command || '';
  if (cmd.length > SPEECH_COMMAND_MAX) cmd = cmd.slice(0, SPEECH_COMMAND_MAX) + '…';
  return `명령 ${cmd} 를 실행할까요. ${alwaysPattern ? '허용, 항상, 거부' : '허용, 거부'}.`;
}

// 전사 한 줄을 allow / always / deny / unclear 로. 순수 함수라 몇 번 불러도 같다.
export function parseApprovalAnswer(text, hasAlways) {
  const t = text.toLowerCase().replace(/[\s.,!?…~]/g, '');
  if (VOICE_DENY.some((w) => t.includes(w))) return 'deny';
  if (hasAlways && VOICE_ALWAYS.some((w) => t.includes(w))) return 'always';
  if (VOICE_ALLOW.some((w) => t.includes(w)) || VOICE_YES.includes(t)) return 'allow';
  return 'unclear';
}

// 열린 모달에 음성으로 답한다. 처리했으면 되읽을 문장, 모달이 없거나 분류 중에 닫혔으면 null.
export async function answerApprovalByVoice(text) {
  if (!_currentId) return null;
  const id = _currentId;
  const hasAlways = !!_alwaysPattern;
  let choice = parseApprovalAnswer(text, hasAlways);
  if (choice === 'unclear') choice = await classifyReply('approval', id, text, _currentCommand, hasAlways);
  if (_currentId !== id) return null;  // 기다리는 사이 클릭이나 다른 창이 답했다
  if (choice !== 'allow' && choice !== 'always') choice = 'deny';
  answer(choice !== 'deny', choice === 'always');
  return HEARD_SPEECH[choice];
}

function answer(approved, always = false) {
  if (!_currentId) return;
  send({ type: 'approval_response', id: _currentId, approved, always });
  $overlay.classList.add('hidden');
  _currentId = null;
  _alwaysPattern = null;
  _currentCommand = '';
}

$allow.addEventListener('click',  () => answer(true));
$deny.addEventListener('click',   () => answer(false));
$always.addEventListener('click', () => answer(true, true));
// Enter → 이번 한 번 허용
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !$overlay.classList.contains('hidden')) {
    e.preventDefault();
    answer(true);
  }
});
