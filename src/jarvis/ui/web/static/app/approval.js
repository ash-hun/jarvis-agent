// 도구 실행 승인 모달 — ALLOW(이번 한 번) · ALWAYS(패턴을 규칙으로) · DENY.
import { send } from './ws.js';

const $overlay = document.getElementById('approval-overlay');
const $reason  = document.getElementById('approval-reason');
const $command = document.getElementById('approval-command');
const $allow   = document.getElementById('btn-allow');
const $deny    = document.getElementById('btn-deny');
const $always  = document.getElementById('btn-always');

let _currentId = null;

export function showApproval(id, command, reason, alwaysPattern) {
  _currentId = id;
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
  $overlay.classList.remove('hidden');
}

function answer(approved, always = false) {
  if (!_currentId) return;
  send({ type: 'approval_response', id: _currentId, approved, always });
  $overlay.classList.add('hidden');
  _currentId = null;
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
