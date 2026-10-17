// Focus 모드 — 서버의 focus_state, focus_panel 을 받아 body[data-focus] 와 구체 둘레 네 영역을 그린다.
// 상태는 서버가 매번 전체를 보내므로 받은 것으로 덮어쓴다. 재접속, 중복 수신에도 화면이 같다.
import { renderMarkdown } from './markdown.js';
import { scrollToEnd } from './messages.js';

const $ring = document.getElementById('focus-ring');
const $task = document.getElementById('focus-task');
const $percent = document.getElementById('focus-percent');
const $eta = document.getElementById('focus-eta');
const $bar = document.getElementById('focus-bar-fill');
const $steps = document.getElementById('focus-steps');
const $elapsed = document.getElementById('focus-elapsed');
const $chatToggle = document.getElementById('chat-toggle');
const $chatCard = document.querySelector('.chat-card');

const TICK_MS = 1000;
// 음성 키워드. 브라우저 인식은 "포커스" 를 "버스", "포커" 처럼 자주 틀리고, 헤드셋은 첫 마디를 흘린다.
// 그래서 비슷한 소리도 "모드" 가 붙으면 받고, 키워드를 문장 끝에 둬도 받는다
const KEY_EXACT = '포커스|포커즈|퍼커스|focus';
const KEY_FUZZY = '버스|보커스|포카스|포커|퍼커|포스';
const MODE = '(?:모드|mode)';
const KEY_STOP = `(?:(?:${KEY_EXACT})\\s*${MODE}?|(?:${KEY_FUZZY})\\s*${MODE})`;
const KEY_START = `(?:${KEY_EXACT}|${KEY_FUZZY})\\s*${MODE}`;
const SPEECH_STOP = new RegExp(`^\\s*${KEY_STOP}\\s*(?:를|은|는)?\\s*(?:종료|끝내|끝|꺼|그만|off|stop)`, 'i');
const SPEECH_START = new RegExp(`^\\s*${KEY_START}\\s*(?:로|으로)?\\s*(?:시작해\\s*줘|시작|켜\\s*줘|켜|해\\s*줘|on)?\\s*[,.:!]?\\s*(.*)$`, 'i');
const SPEECH_START_TAIL = new RegExp(
  `^(.+?)[\\s,.]*${KEY_START}\\s*(?:로|으로)?\\s*(?:시작해\\s*줘|시작|진행해\\s*줘|진행|해\\s*줘|켜|on)?[\\s.!]*$`, 'i');
// Focus 중에는 "포커스 모드" 가 잘려도 끝내는 말만으로 끝낸다. "동요" 는 "종료" 를 잘못 들은 실측 전사다
const SPEECH_STOP_BARE = new RegExp(
  `^\\s*(?:${KEY_STOP}\\s*)?(?:모드\\s*)?(?:를|은|는)?\\s*(?:종료|동요|끝내|끝|그만|꺼|off|stop)` +
  `\\s*(?:해\\s*줘|해|할게|하자|합니다|해요)?[\\s.!]*$`, 'i');

let _state = null;          // 마지막 focus_state (active=true 일 때만)
let _receivedAt = 0;        // 그 상태를 받은 시각. 경과 시간을 화면에서 이어 센다
let _timer = null;

export function isFocusOn() { return _state !== null; }

// 전사 한 줄을 /focus 명령으로. 키워드가 없으면 null — 평소 대화로 보낸다
export function focusCommandFromSpeech(text) {
  if (SPEECH_STOP.test(text) || (isFocusOn() && SPEECH_STOP_BARE.test(text))) return '/focus stop';
  const m = text.match(SPEECH_START) || text.match(SPEECH_START_TAIL);
  if (!m) return null;
  const task = m[1].trim().replace(/[\s,.]+$/, '');
  return task ? `/focus ${task}` : '/focus';
}

function fmtClock(sec) {
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const mm = String(m).padStart(2, '0'), ss = String(r).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function fmtEta(sec) {
  if (sec === null || sec === undefined) return '예상 시간 계산 중';
  if (sec < 60) return '곧 완료';
  const min = Math.round(sec / 60);
  return min >= 60 ? `약 ${Math.floor(min / 60)}시간 ${min % 60}분 남음` : `약 ${min}분 남음`;
}

function setFocusBody(on) {
  if (on) document.body.dataset.focus = 'on';
  else delete document.body.dataset.focus;
  $ring.setAttribute('aria-hidden', on ? 'false' : 'true');
  if (!on) document.body.classList.remove('focus-chat-open');
}

function tick() {
  if (!_state) return;
  const elapsed = _state.elapsed_sec + (Date.now() - _receivedAt) / 1000;
  $elapsed.textContent = fmtClock(elapsed);
}

function renderState(st) {
  $task.textContent = st.task || '';
  const pct = Math.round((st.progress || 0) * 100);
  $percent.textContent = `${pct}%`;
  $bar.style.width = `${pct}%`;
  $eta.textContent = pct >= 100 ? '완료' : fmtEta(st.eta_sec);
  $steps.replaceChildren(...(st.steps || []).map((step) => {
    const li = document.createElement('li');
    li.className = step.done ? 'done' : '';
    li.textContent = step.title;
    return li;
  }));
  $steps.dataset.empty = st.steps && st.steps.length ? '' : '단계를 나누는 중입니다';
  tick();
}

export function onFocusState(st) {
  if (!st || !st.active) {
    _state = null;
    clearInterval(_timer);
    _timer = null;
    setFocusBody(false);
    return;
  }
  _state = st;
  _receivedAt = Date.now();
  setFocusBody(true);
  renderState(st);
  if (!_timer) _timer = setInterval(tick, TICK_MS);
}

export function onFocusPanel(area, markdown, busy) {
  const panel = $ring.querySelector(`.focus-panel[data-area="${area}"]`);
  if (!panel) return;
  const body = panel.querySelector('.focus-body');
  panel.classList.toggle('busy', !!busy);
  // 기록은 아래로 쌓이니 끝을, 조사와 분석은 처음을 보여 준다
  const atEnd = area === 'log';
  body.innerHTML = markdown ? renderMarkdown(markdown) : '';
  if (atEnd) body.scrollTop = body.scrollHeight;
}

// 세션을 바꾸면 그 세션의 상태를 서버가 다시 보낸다. 그 전까지는 Default 로 둔다
export function resetFocus() {
  onFocusState(null);
  $ring.querySelectorAll('.focus-body').forEach((b) => { b.innerHTML = ''; });
}

// Focus 동안 접힌 띠 가운데 Conversation 만 눌러서 펼친다. 다른 띠는 반응하지 않는다(CSS pointer-events)
$chatToggle.addEventListener('click', (e) => {
  if (!isFocusOn()) return;
  e.stopImmediatePropagation();
  const open = document.body.classList.toggle('focus-chat-open');
  if (open) scrollToEnd();
}, true);

// 펼친 대화 밖을 누르면 닫는다
document.addEventListener('pointerdown', (e) => {
  if (!document.body.classList.contains('focus-chat-open')) return;
  if ($chatCard.contains(e.target) || e.target.closest('.composer')) return;
  document.body.classList.remove('focus-chat-open');
});
