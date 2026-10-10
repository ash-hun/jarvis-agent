// 음성 입출력 배선 — 구체 클릭으로 켜고, 전사는 입력창과 같은 길로 보낸다.
import { send } from './ws.js';
import { escapeHtml } from './markdown.js';
import { setStatus, currentStatus } from './shell.js';
import { appendMsg } from './messages.js';
import { tryProactiveFeedback } from './proactive.js';
import { sendUserText, setInputEnabled, updateHighlight } from './composer.js';

const $sphereWrap = document.querySelector('.sphere-wrap');
const $sphereHit  = document.getElementById('sphere-hit');
const $input      = document.getElementById('chat-input');

let _voiceMode = false;  // 현재 요청이 음성으로 시작됐는지 — 응답을 읽어줄지 정한다

export function isVoiceMode() { return _voiceMode; }
export function clearVoiceMode() { _voiceMode = false; }

export const voice = new VoiceManager({
  onTranscript(transcript) {
    if (!transcript.trim()) return;
    // proactive 직후 짧은 음성 답을 수락/무시로 해석 (C3, voice).
    if (tryProactiveFeedback(transcript)) return;
    _voiceMode = true;
    $input.value = transcript;   // 인식된 텍스트를 잠깐 입력창에 비춘다
    updateHighlight();
    appendMsg('USER', 'user', escapeHtml(transcript));
    $input.value = '';
    updateHighlight();
    sendUserText(transcript);
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
      // idle: TTS 종료 or 오류 → input 복원 + 상태 표시 초기화
      if (currentStatus() === 'LISTENING' || currentStatus() === 'SPEAKING') {
        setStatus('READY');
        HUD.setState('idle');
      }
      setInputEnabled(true);
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
export function requestSpeech(text) {
  voice.setProcessing();
  send({ type: 'voice_tts_request', text });
}

// 구체 클릭 → voice mode 토글
$sphereHit.addEventListener('click', () => {
  if (!voice.supported) {
    appendMsg('SYS', 'err', 'Web Speech API를 지원하지 않는 브라우저입니다. Chrome을 사용해 주세요.');
    return;
  }
  voice.toggle();
});
