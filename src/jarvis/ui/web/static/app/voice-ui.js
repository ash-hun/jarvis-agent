// 음성 입출력 배선 — 구체 클릭으로 켜고, 전사는 입력창과 같은 길로 보낸다. Full-voice 면 읽은 뒤 다시 듣는다.
import { sendUserText, setInputEnabled, updateHighlight } from './composer.js';
import { setStatus, currentStatus, logActivity } from './shell.js';
import { isFullVoice, onModeChange, setMode } from './mode.js';
import { tryProactiveFeedback } from './proactive.js';
import { answerApprovalByVoice, isApprovalOpen } from './approval.js';
import { escapeHtml } from './markdown.js';
import { isAgentBusy } from './events.js';
import { appendMsg } from './messages.js';
import { focusCommandFromSpeech } from './focus.js';
import { send } from './ws.js';

// TTS 꼬리가 마이크에 들어가지 않게 읽기가 끝난 뒤 잠깐 쉬고 듣는다
const LISTEN_AFTER_SPEECH_MS = 250;
const UNSUPPORTED_MSG = 'Web Speech API를 지원하지 않는 브라우저입니다. Chrome을 사용해 주세요.';

const $sphereWrap = document.querySelector('.sphere-wrap');
const $sphereHit  = document.getElementById('sphere-hit');
const $input      = document.getElementById('chat-input');

let _voiceMode = false;    // 현재 요청이 음성으로 시작됐는지 — 응답을 읽어줄지 정한다
let _thenListen = null;    // 마지막 읽기 요청이 끝났을 때 다시 들을지 묻는 함수

export function isVoiceMode() { return _voiceMode; }
export function clearVoiceMode() { _voiceMode = false; }

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
    // Full-voice 에서 승인 모달이 열려 있으면 이 답은 승인이다. 메시지로 보내지 않는다.
    if (isFullVoice() && isApprovalOpen()) {
      showUser(transcript);
      const heard = await answerApprovalByVoice(transcript);
      if (!heard) { voice.setIdle(); return; }  // 분류 중에 클릭이나 다른 창이 먼저 답했다
      appendMsg('SYS', 'sys', escapeHtml(heard));
      logActivity(`⚡ approval · 음성 · ${heard}`, 'tool');
      requestSpeech(heard);
      return;
    }
    // proactive 직후 짧은 음성 답을 수락/무시로 해석 (C3, voice).
    if (await tryProactiveFeedback(transcript)) { voice.setIdle(); return; }
    _voiceMode = true;
    showUser(transcript);
    // "포커스 모드 <작업>", "포커스 모드 종료" 는 /focus 명령으로 보낸다
    const command = [transcript, ...alternatives].map(focusCommandFromSpeech).find(Boolean);
    sendUserText(command || transcript);
  },
  onStateChange(state) {
    $sphereWrap.classList.remove('voice-listening', 'voice-speaking', 'voice-processing');
    if (state !== 'idle') $sphereWrap.classList.add(`voice-${state}`);

    if (state === 'listening') {
      setStatus('LISTENING', 'listening');
      HUD.setState('listening');
    } else if (state === 'speaking') {
      setStatus('SPEAKING', 'speaking');
      HUD.setState('speaking');
    } else if (state === 'processing') {
      // 에이전트 처리 중 — 기존 UI가 담당
    } else {
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
      const thenListen = _thenListen;
      _thenListen = null;
      if (thenListen && thenListen()) setTimeout(() => voice.start(), LISTEN_AFTER_SPEECH_MS);
    }
  },
  onError(msg) {
    appendMsg('SYS', 'err', escapeHtml(msg));
  },
  onAudioCaptured(base64, mime) {
    // 서버 STT 모드: 녹음된 오디오를 백엔드로 전송 → voice_stt_result 수신
    send({ type: 'voice_stt_submit', data: base64, mime, sample_rate: 16000 });
  },
});
window.voiceManager = voice;

// 텍스트를 읽어 달라고 서버에 요청한다. 응답은 voice_tts_audio 로 온다.
// thenListen 은 읽기가 끝난 시점에 평가한다. 그사이 모달이 닫혔으면 듣지 않는다.
export function requestSpeech(text, { thenListen = null } = {}) {
  _thenListen = thenListen;
  voice.setProcessing();
  send({ type: 'voice_tts_request', text });
}

// 구체 클릭 → voice mode 토글
$sphereHit.addEventListener('click', () => {
  if (!voice.supported) {
    appendMsg('SYS', 'err', UNSUPPORTED_MSG);
    return;
  }
  voice.toggle();
});

// Full-voice 동안은 마이크를 잡아 둔다. 듣기와 읽기를 오갈 때마다 블루투스 프로필이 바뀌면 연결이 흔들린다.
voice.setHoldMic(isFullVoice());

// Full-voice 로 바꾼 클릭이 사용자 제스처라 그때 마이크를 연다. 되돌리면 듣던 것을 멈추고 마이크를 놓는다.
onModeChange((mode) => {
  if (mode === 'full-voice') {
    if (!voice.supported) {
      appendMsg('SYS', 'err', UNSUPPORTED_MSG);
      setMode('default');
      return;
    }
    voice.setHoldMic(true);
    voice.start();
  } else {
    _thenListen = null;
    voice.setHoldMic(false);
    voice.stop();
  }
});
