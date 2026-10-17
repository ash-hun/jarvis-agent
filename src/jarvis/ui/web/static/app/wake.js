// 웨이크워드 — 모드와 상관없이 기다리는 동안 마이크를 16kHz PCM 으로 서버에 흘리고, voice_wake 가 오면 듣기를 연다.
import { sendBinary } from './ws.js';
import { logActivity } from './shell.js';
import { isAgentBusy } from './events.js';
import { isApprovalOpen } from './approval.js';
import { voice, isSpeechActive, cue } from './voice-ui.js';

const SAMPLE_RATE = 16000;
const WORKLET_URL = 'wake-worklet.js';

let _enabled = false;  // 서버가 connected.voice.wake 로 알려 준다
let _ctx = null;
let _stream = null;
let _node = null;

// 듣기, 읽기, 응답, 승인 중에는 보내지 않는다. 그동안의 "Jarvis" 는 대화의 일부다
function waiting() {
  return _enabled && voice.state === 'idle' && !isSpeechActive() && !isAgentBusy() && !isApprovalOpen();
}

// 자동 재생 정책에 걸려 멈춘 컨텍스트는 다음 클릭이나 키 입력에서 깨운다
function resumeOnGesture(ctx) {
  const resume = () => { if (_ctx === ctx) ctx.resume(); };
  document.addEventListener('pointerdown', resume, { once: true });
  document.addEventListener('keydown', resume, { once: true });
}

async function startCapture() {
  if (_ctx || !_enabled || !navigator.mediaDevices?.getUserMedia) return;
  const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
  _ctx = ctx;
  try {
    await ctx.audioWorklet.addModule(WORKLET_URL);
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    if (_ctx !== ctx) { stream.getTracks().forEach((t) => t.stop()); return; }  // 기다리는 사이 껐다
    _stream = stream;
    _node = new AudioWorkletNode(ctx, 'wake-capture');
    _node.port.onmessage = (e) => { if (waiting()) sendBinary(e.data); };
    ctx.createMediaStreamSource(stream).connect(_node);
    if (ctx.state === 'suspended') resumeOnGesture(ctx);
  } catch (e) {
    stopCapture();
    logActivity(`wake word off · ${e.message}`, 'err');
  }
}

function stopCapture() {
  if (_node) _node.port.onmessage = null;
  _node = null;
  if (_stream) _stream.getTracks().forEach((t) => t.stop());
  _stream = null;
  if (_ctx) _ctx.close().catch(() => {});
  _ctx = null;
}

// 접속마다 서버가 알려 준다. 몇 번 불러도 같은 상태로 맞춘다
export function setWakeEnabled(on) {
  _enabled = !!on;
  if (_enabled) startCapture();
  else stopCapture();
}

// "Jarvis" — 대답 문구를 읽고 듣기를 연다. 그사이 다른 일이 시작됐으면 듣지 않는다.
// Default 에서 깨운 요청은 음성으로 시작한 요청이라 응답을 읽어 주고, 다 읽은 뒤 다시 듣지는 않는다
export async function onWake() {
  if (!waiting()) return;
  logActivity('◉ wake · Jarvis');
  await cue('wake_up', { always: true });
  if (waiting()) voice.start();
}
