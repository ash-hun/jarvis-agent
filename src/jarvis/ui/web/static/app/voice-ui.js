// 음성 입출력 배선 — 구체 클릭으로 켜고, 전사는 입력창과 같은 길로 보낸다. 말로 시작한 대화는 읽은 뒤 다시 듣는다.
import { sendUserText, setInputEnabled, updateHighlight } from './composer.js';
import { setStatus, currentStatus, logActivity } from './shell.js';
import { answerApprovalByVoice, isApprovalOpen } from './approval.js';
import { escapeHtml } from './markdown.js';
import { isAgentBusy } from './events.js';
import { appendMsg } from './messages.js';
import { focusCommandFromSpeech } from './focus.js';
import { hasPhrase, phraseWav } from './phrases.js';
import { send } from './ws.js';

// TTS 꼬리가 마이크에 들어가지 않게 읽기가 끝난 뒤 잠깐 쉬고 듣는다
const LISTEN_AFTER_SPEECH_MS = 250;
// 음성 승인 대기 중 다시 듣는 횟수 상한. 인식은 몇 초 말이 없으면 끝나므로 승인 시한(120초) 동안 이어 듣는다
const APPROVAL_LISTEN_MAX = 20;
const UNSUPPORTED_MSG = 'Web Speech API를 지원하지 않는 브라우저입니다. Chrome을 사용해 주세요.';

const $sphereWrap = document.querySelector('.sphere-wrap');
const $sphereHit  = document.getElementById('sphere-hit');
const $input      = document.getElementById('chat-input');

let _voiceMode = false;    // 현재 요청이 음성으로 시작됐는지 — 응답을 읽어줄지 정한다
// 말로 주고받는 중인지. 말로 요청하면 켜지고, 들었는데 말이 없거나, 타이핑하거나, 읽기를 멈추면 꺼진다.
// 켜져 있는 동안 답을 읽은 뒤 다시 듣고, 먼저 건네는 말(🔔)도 읽는다
let _conversing = false;
let _listenPending = false; // 듣기를 시작했고 아직 전사를 받지 못했다
let _thenListen = null;    // 마지막 읽기 요청이 끝났을 때 다시 들을지 묻는 함수
let _speechSeq = 0;
const _awaitingSpeech = new Set();  // 보냈지만 아직 오디오가 오지 않은 읽기 요청 id
let _approvalListens = 0;  // 음성 승인 답을 기다리며 남은 듣기 횟수
let _held = null;          // 사용자가 말하거나 듣는 중이라 미뤄 둔 먼저 건네는 말 { text, opts }

export function isVoiceMode() { return _voiceMode; }
export function clearVoiceMode() { _voiceMode = false; }
export function isConversing() { return _conversing; }

function endConversation() {
  _conversing = false;
  _listenPending = false;
}

function showUser(text) {
  $input.value = text;   // 인식된 텍스트를 잠깐 입력창에 비춘다
  updateHighlight();
  appendMsg('USER', 'user', escapeHtml(text));
  $input.value = '';
  updateHighlight();
}

export const voice = new VoiceManager({
  async onTranscript(transcript, alternatives = []) {
    if (!transcript.trim()) return;
    _listenPending = false;
    // 승인 모달이 열려 있으면 이 답은 승인이다. 메시지로 보내지 않는다.
    if (isApprovalOpen()) {
      showUser(transcript);
      const heard = await answerApprovalByVoice(transcript);
      if (!heard) { voice.setIdle(); return; }  // 분류 중에 클릭이나 다른 창이 먼저 답했다
      appendMsg('SYS', 'sys', escapeHtml(heard));
      logActivity(`⚡ approval · 음성 · ${heard}`, 'tool');
      requestSpeech(heard, { source: 'approval_answer' });
      return;
    }
    _voiceMode = true;
    _conversing = true;
    showUser(transcript);
    // "포커스 모드 <작업>", "포커스 모드 종료" 는 /focus 명령으로 보낸다
    const command = [transcript, ...alternatives].map(focusCommandFromSpeech).find(Boolean);
    sendUserText(command || transcript);
  },
  onStateChange(state) {
    $sphereWrap.classList.remove('voice-listening', 'voice-speaking', 'voice-processing');
    if (state !== 'idle') $sphereWrap.classList.add(`voice-${state}`);

    if (state === 'listening') {
      _listenPending = true;
      setStatus('LISTENING', 'listening');
      HUD.setState('listening');
    } else if (state === 'speaking') {
      setStatus('SPEAKING', 'speaking');
      HUD.setState('speaking');
    } else if (state === 'processing') {
      // 에이전트 처리 중 — 기존 UI가 담당
    } else {
      // 들었는데 말이 없었다(무음, 못 알아들음, 다시 눌러 취소). 대화를 끝낸다. 음성 승인을 기다리는 중이면 이어 듣는다
      if (_listenPending && !isApprovalOpen()) endConversation();
      // idle: TTS 종료 or 오류. 에이전트가 아직 일하는 중이면(승인 되읽기 등) 입력을 열지 않는다.
      if (isAgentBusy()) {
        setStatus('THINKING', 'thinking');
        HUD.setState('thinking');
      } else {
        if (currentStatus() === 'LISTENING' || currentStatus() === 'SPEAKING') {
          setStatus('READY');
          HUD.setState('idle');
        }
        setInputEnabled(true);
      }
      // 말을 끊지 않으려고 미뤄 둔 말이 있으면 지금 한다. 그 말의 thenListen 이 다음 듣기를 정한다
      if (_held && !isAgentBusy()) {
        const { text, opts } = _held;
        _held = null;
        requestSpeech(text, opts);
        return;
      }
      const thenListen = _thenListen;
      _thenListen = null;
      if (thenListen && thenListen()) setTimeout(() => voice.start(), LISTEN_AFTER_SPEECH_MS);
      else listenAgainForApproval();
    }
  },
  onError(msg) {
    _approvalListens = 0;  // 권한 거부 같은 인식 오류에서 듣기를 되풀이하지 않는다
    appendMsg('SYS', 'err', escapeHtml(msg));
  },
  onFallback(reason) {
    logActivity(`voice · 브라우저 인식 불가(${reason}) → 서버 인식`, 'sys');
  },
  onAudioCaptured(base64, mime) {
    // 서버 STT 모드: 녹음된 오디오를 백엔드로 전송 → voice_stt_result 수신
    send({ type: 'voice_stt_submit', data: base64, mime, sample_rate: 16000 });
  },
});
window.voiceManager = voice;

// 미리 녹음한 문구를 읽는다. 말로 주고받는 중일 때만, always 면 늘.
// 문구가 없거나 받지 못하면 false 를 돌려 부른 쪽이 원래대로(합성) 하게 한다
export async function cue(name, { always = false } = {}) {
  if (!hasPhrase(name) || !(always || _conversing || _voiceMode)) return false;
  const wav = await phraseWav(name);
  if (!wav) return false;
  send({ type: 'voice_spoken', phrase: name });  // 서버가 이 문구의 문장을 밖에 알린다
  await voice.playWav(wav);
  return true;
}

// 텍스트를 읽어 달라고 서버에 요청한다. 응답은 voice_tts_audio 로 온다.
// thenListen 은 읽기가 끝난 시점에 평가한다. 그사이 모달이 닫혔으면 듣지 않는다.
// source 는 무엇을 읽는지(reply, filler, proactive, reminder, approval, approval_answer)다.
// 서버가 읽는 말을 밖(디스코드)에도 알릴 때 이미 따로 보낸 🔔, ⏰ 을 거른다
export function requestSpeech(text, { thenListen = null, source = '' } = {}) {
  _thenListen = thenListen;
  voice.setProcessing();
  const id = ++_speechSeq;
  _awaitingSpeech.add(id);
  // stream: 서버가 문장마다 합성해 보낸다. 첫 문장을 읽는 동안 다음 문장을 합성해 첫 소리가 빨라진다
  send({ type: 'voice_tts_request', text, id, source, stream: true });
}

// 먼저 건네는 말을 읽는다. 사용자가 말하거나 듣거나 다른 말을 읽는 중이면 끊지 않고 끝날 때까지 미룬다.
// 미뤄 둔 말은 하나만 둔다. 더 새 말이 오면 그것으로 바꾼다
export function speakWhenFree(text, opts = {}) {
  if (voice.state === 'idle' && !isSpeechActive() && !isAgentBusy()) requestSpeech(text, opts);
  else _held = { text, opts };
}

// 음성 승인 답을 기다린다. 질문이나 다른 읽기가 끝날 때, 인식이 말 없이 끝날 때마다 다시 듣는다.
// 한 번만 들으면 늦게 말하거나 다른 읽기가 끼어든 답을 놓쳐 120초 뒤 거부된다
export function listenForApproval() { _approvalListens = APPROVAL_LISTEN_MAX; }

function listenAgainForApproval() {
  if (_approvalListens <= 0) return;
  if (!isApprovalOpen()) { _approvalListens = 0; return; }
  if (isSpeechActive()) return;  // 읽는 동안 들으면 질문 자체를 답으로 듣는다
  _approvalListens -= 1;
  setTimeout(() => {
    if (isApprovalOpen() && !isSpeechActive()) voice.start();
  }, LISTEN_AFTER_SPEECH_MS);
}

// 도착한 합성 결과를 읽을지. 멈춘 뒤에 늦게 온 결과는 버린다. id 없는 결과(옛 서버)는 읽는다.
// more 면 같은 읽기의 문장이 더 온다. 마지막 문장에서 기다림을 끝낸다
export function takeSpeech(id, more = false) {
  if (id === null || id === undefined) return true;
  return more ? _awaitingSpeech.has(id) : _awaitingSpeech.delete(id);
}

export function isSpeechActive() {
  return voice.state === 'speaking' || _awaitingSpeech.size > 0;
}

// 읽던 것과 기다리던 읽기를 모두 멈춘다. 멈추면 말로 주고받던 대화도 끝나 다시 듣지 않는다
export function stopSpeech() {
  endConversation();
  _held = null;
  _awaitingSpeech.clear();
  _thenListen = null;
  _approvalListens = 0;
  voice.stopSpeaking();
}

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !isSpeechActive()) return;
  e.preventDefault();
  stopSpeech();
});

// 구체 클릭과 데스크톱 전역 단축키 → 듣기 토글. 읽는 중이면 멈춘다
export function listenNow() {
  if (isSpeechActive()) { stopSpeech(); return; }
  if (!voice.supported) {
    appendMsg('SYS', 'err', UNSUPPORTED_MSG);
    return;
  }
  voice.toggle();
}

$sphereHit.addEventListener('click', listenNow);

// 타이핑해서 보내면 말로 주고받던 대화는 끝난다. 답은 화면에만 보인다
document.getElementById('composer').addEventListener('submit', endConversation);
