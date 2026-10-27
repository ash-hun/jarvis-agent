'use strict';

/**
 * VoiceManager
 *
 * STT : 브라우저 Web Speech API (기본값) 또는 백엔드 Whisper
 * TTS : 백엔드 Supertonic-3 WAV 스트림 (기본값) 또는 브라우저 Web Speech API fallback
 *
 * 상태 머신: idle → listening → processing → (idle or speaking) → idle
 *
 * 생성자 options:
 *   onTranscript(text, alts)  — STT 결과 콜백. alts 는 같은 발화의 다른 인식 후보
 *   onStateChange(state)      — 상태 변경 콜백 ('idle'|'listening'|'processing'|'speaking')
 *   onError(msg)              — 에러 콜백
 *   onAudioCaptured(b64,mime) — 서버 STT 모드에서 녹음된 오디오를 백엔드로 보낼 때 호출
 *   lang                      — STT 언어 (기본 'ko-KR')
 *
 * STT 모드:
 *   'browser' (기본) — Web Speech API가 브라우저에서 인식
 *   'server'         — MediaRecorder로 녹음 → onAudioCaptured로 백엔드 전송 → receiveTranscript로 결과 수신
 */
// 블루투스 헤드셋은 인식이 닫힌 직후 오디오 경로를 다시 잡으며 그사이 소리를 버린다.
// 마이크 스트림을 잡아 둬도 인식 쪽 캡처는 닫히므로, 인식 직후의 읽기는 늘 잠깐 쉬고 시작한다.
const MIC_SETTLE_MS = 600;
// onend 가 오지 않는 브라우저에서도 읽기가 막히지 않게 기다림에 상한을 둔다
const MIC_RELEASE_TIMEOUT_MS = 1500;
// speak 뒤 이 시간 안에 start 가 오지 않으면 브라우저가 문장을 버린 것으로 보고 한 번만 다시 읽는다
const TTS_START_TIMEOUT_MS = 1500;
const TTS_RETRY_GAP_MS = 150;
const STT_ALTERNATIVES = 3;

class VoiceManager {
  constructor({ onTranscript, onStateChange, onError, onAudioCaptured, lang = 'ko-KR' } = {}) {
    this._state         = 'idle';
    this._onTranscript  = onTranscript    || (() => {});
    this._onState       = onStateChange   || (() => {});
    this._onError       = onError         || (() => {});
    this._onAudioCaptured = onAudioCaptured || (() => {});
    this._lang          = lang;
    this._audioCtx      = null;
    this._source        = null;   // 재생 중인 서버 TTS 오디오. 멈출 때 끊는다
    this._speakGen      = 0;      // stopSpeaking 마다 오른다. 준비 중이던 읽기는 끝나고 보면 낡았다

    // ── 마이크 점유: 인식 중인지, 언제 놓았는지, 계속 잡아 둘 스트림 ─────────────────
    this._micOpen       = false;
    this._micReleasedAt = -Infinity;
    this._releaseWaiters = [];
    this._holdWanted    = false;
    this._heldStream    = null;

    // ── 서버 STT 모드용 녹음 상태 ───────────────────────────────────────────────
    this._sttMode       = 'browser';
    this._mediaRecorder = null;
    this._mediaStream   = null;
    this._chunks        = [];

    // ── STT: Web Speech API ───────────────────────────────────────────────────
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    this._recognition = SR ? new SR() : null;

    if (this._recognition) {
      this._recognition.lang           = this._lang;
      this._recognition.continuous     = false;
      this._recognition.interimResults = true;
      // 첫 후보가 틀려도 다른 후보에 명령 키워드가 있을 수 있다
      this._recognition.maxAlternatives = STT_ALTERNATIVES;

      this._recognition.onresult = (e) => {
        const results    = Array.from(e.results);
        const transcript = results.map(r => r[0].transcript).join('');
        if (results[results.length - 1].isFinal) {
          this._setState('processing');
          // 최종 결과 뒤에도 인식은 잠깐 열려 있다. 바로 닫아 읽기가 기다리는 시간을 줄인다.
          try { this._recognition.stop(); } catch (_) {}
          const last = results[results.length - 1];
          const alternatives = results.length === 1
            ? Array.from(last).slice(1).map(a => a.transcript)
            : [];
          this._onTranscript(transcript, alternatives);
        }
      };

      this._recognition.onend = () => {
        this._markMicReleased();
        if (this._state === 'listening') this._setState('idle');
      };

      this._recognition.onerror = (e) => {
        this._markMicReleased();
        this._setState('idle');
        if (e.error !== 'no-speech' && e.error !== 'aborted') {
          this._onError(`STT 오류: ${e.error}`);
        }
      };
    }
  }

  // ── 공개 API ────────────────────────────────────────────────────────────────

  get supported() {
    if (this._sttMode === 'server') {
      return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    }
    return !!this._recognition;
  }
  get state() { return this._state; }

  /** STT 처리 위치 설정 — 'browser' | 'server' (백엔드 connected 메시지로 결정) */
  setSttMode(mode) { this._sttMode = (mode === 'server') ? 'server' : 'browser'; }

  /** 음성 인식 토글 (idle ↔ listening) */
  toggle() {
    if (this._state === 'idle')      this.start();
    else if (this._state === 'listening') this.stop();
  }

  start() {
    if (this._state !== 'idle') return;
    if (this._sttMode === 'server') {
      this._startServerRecording();
      return;
    }
    if (!this._recognition) {
      this._onError('이 브라우저는 Web Speech API를 지원하지 않습니다. Chrome을 사용해 주세요.');
      return;
    }
    this._acquireHeldMic();
    try {
      this._recognition.start();
      this._micOpen = true;
      this._setState('listening');
    } catch (e) {
      this._setState('idle');
      this._onError(`마이크 시작 실패: ${e.message}`);
    }
  }

  stop() {
    if (this._state !== 'listening') return;
    if (this._sttMode === 'server') {
      this._stopServerRecording();
      return;
    }
    try { this._recognition?.stop(); } catch (_) {}
    this._setState('idle');
  }

  /**
   * 켜 두면 마이크 스트림을 계속 잡아 블루투스 헤드셋이 듣기와 읽기 사이에 프로필을 바꾸지 않게 한다.
   * 대신 그동안 출력은 통화 음질이 된다. 스트림은 다음 start() 에서 잡는다(권한 요청이 그 시점에 뜨도록).
   */
  setHoldMic(on) {
    this._holdWanted = !!on;
    if (!on && this._heldStream) {
      this._heldStream.getTracks().forEach(t => t.stop());
      this._heldStream = null;
    }
  }

  /** 서버 STT 결과(전사 텍스트)를 수신해 onTranscript로 전달한다. */
  receiveTranscript(text) {
    if (!text || !text.trim()) { this._setState('idle'); return; }
    this._onTranscript(text);
  }

  /** 에이전트 응답 처리 중 상태 표시용 */
  setProcessing() { this._setState('processing'); }
  setIdle()       { this._setState('idle'); }

  /** 읽던 것을 끊는다. 준비 중(마이크 반납 대기, 디코딩)인 읽기도 시작하지 않는다. 여러 번 불러도 같다. */
  stopSpeaking() {
    this._speakGen += 1;
    if (this._source) {
      const source = this._source;
      this._source = null;
      source.onended = null;
      try { source.stop(); } catch (_) {}
    }
    const done = this._sourceDone;
    this._sourceDone = null;
    if (done) done();
    if (this._utterance) this._utterance = null;  // 끊긴 문장의 onend 가 상태를 건드리지 않게
    if (window.speechSynthesis && (window.speechSynthesis.speaking || window.speechSynthesis.pending)) {
      window.speechSynthesis.cancel();
    }
    if (this._state === 'speaking' || this._state === 'processing') this._setState('idle');
  }

  /**
   * 서버가 문장마다 보내는 합성 결과를 앞 문장이 끝난 뒤에 이어 읽는다.
   * more 면 뒤 문장이 온다. 문장 사이에 idle 로 내려가지 않아야 다 읽기 전에 듣기를 시작하지 않는다.
   * 멈추면(stopSpeaking) 줄 서 있던 문장도 읽지 않는다.
   */
  queueAudioBase64(base64Data, more = false, mimeType = 'audio/wav') {
    const gen = this._speakGen;
    const bytes = Uint8Array.from(atob(base64Data), c => c.charCodeAt(0));
    this._playChain = (this._playChain || Promise.resolve())
      .then(() => (gen === this._speakGen ? this.playWav(bytes.buffer, { more }) : undefined));
    return this._playChain;
  }

  /**
   * WAV 바이트를 재생한다. 미리 녹음한 문구도 이 길로 읽는다.
   * @param {ArrayBuffer} wav
   * @param {{more?: boolean}} opts more 면 끝나도 speaking 으로 남는다(이어 읽을 문장이 있다)
   * @returns {Promise<void>} 끝나거나 멈추거나 실패하면 풀린다
   */
  async playWav(wav, { more = false } = {}) {
    const gen = this._speakGen;
    this._setState('speaking');
    await this._afterMicReleased();
    if (gen !== this._speakGen) return;
    try {
      if (!this._audioCtx || this._audioCtx.state === 'closed') {
        this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      // Suspended context (autoplay policy) 해제
      if (this._audioCtx.state === 'suspended') await this._audioCtx.resume();

      const buffer = await this._audioCtx.decodeAudioData(wav.slice(0));
      if (gen !== this._speakGen) return;
      const source = this._audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(this._audioCtx.destination);
      await new Promise((resolve) => {
        this._sourceDone = resolve;  // stopSpeaking 이 onended 를 떼어도 기다리는 쪽이 풀리게
        source.onended = () => {
          resolve();
          if (this._source !== source) return;
          this._source = null;
          if (!more) this._setState('idle');
        };
        this._source = source;
        source.start(0);
      });
    } catch (e) {
      console.error('[VoiceManager] Audio playback failed:', e);
      this._setState('idle');
    }
  }

  /**
   * 브라우저 내장 TTS로 텍스트를 읽는다 (백엔드 TTS 없을 때 fallback).
   * @param {string} text
   * @param {string} lang
   */
  async speakBrowser(text, lang = this._lang) {
    if (!window.speechSynthesis) { this._setState('idle'); return; }
    const gen = this._speakGen;
    this._setState('speaking');
    await this._afterMicReleased();
    if (gen !== this._speakGen) return;
    // Chrome 은 cancel 직후의 speak 를 소리 없이 버릴 때가 있어, 읽는 게 있을 때만 끊는다
    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) window.speechSynthesis.cancel();
    this._speakUtterance(text, lang, true);
  }

  _speakUtterance(text, lang, retry) {
    const u  = new SpeechSynthesisUtterance(text);
    u.lang   = lang;
    u.rate   = 1.0;
    this._utterance = u;  // Chrome 이 재생 중인 utterance 를 수거해 onend 를 잃지 않게 잡아 둔다
    let started = false;
    u.onstart = () => { started = true; console.info('[voice] tts start', text.slice(0, 20)); };
    u.onend   = () => { if (this._utterance === u) this._setState('idle'); };
    u.onerror = (e) => {
      console.warn('[voice] tts error', e.error, text.slice(0, 20));
      if (this._utterance === u) this._setState('idle');
    };
    window.speechSynthesis.speak(u);
    setTimeout(() => {
      if (started || this._utterance !== u) return;
      console.warn('[voice] tts did not start', retry ? 'retrying' : 'giving up', text.slice(0, 20));
      this._utterance = null;  // 끊긴 문장의 onerror 가 상태를 idle 로 돌리지 않게
      window.speechSynthesis.cancel();
      if (retry) setTimeout(() => this._speakUtterance(text, lang, false), TTS_RETRY_GAP_MS);
      else this._setState('idle');
    }, TTS_START_TIMEOUT_MS);
  }

  // ── 서버 STT 녹음 (MediaRecorder) ─────────────────────────────────────────────

  async _startServerRecording() {
    if (!this.supported) {
      this._onError('이 브라우저는 마이크 녹음(MediaRecorder)을 지원하지 않습니다.');
      return;
    }
    try {
      this._mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      this._setState('idle');
      this._onError(`마이크 접근 실패: ${e.message}`);
      return;
    }
    this._chunks = [];
    this._mediaRecorder = new MediaRecorder(this._mediaStream);
    this._mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size) this._chunks.push(e.data); };
    this._mediaRecorder.onstop = () => this._finalizeRecording();
    this._mediaRecorder.start();
    this._setState('listening');
  }

  _stopServerRecording() {
    if (this._mediaRecorder && this._mediaRecorder.state !== 'inactive') {
      this._mediaRecorder.stop();  // onstop → _finalizeRecording
    }
    if (this._mediaStream) {
      this._mediaStream.getTracks().forEach(t => t.stop());
      this._mediaStream = null;
    }
  }

  async _finalizeRecording() {
    const mime = this._mediaRecorder?.mimeType || 'audio/webm';
    const blob = new Blob(this._chunks, { type: mime });
    this._chunks = [];
    if (!blob.size) { this._setState('idle'); return; }
    this._setState('processing');  // 백엔드 전사 대기
    try {
      const b64 = await this._blobToBase64(blob);
      this._onAudioCaptured(b64, mime);
    } catch (e) {
      this._setState('idle');
      this._onError(`오디오 인코딩 실패: ${e.message}`);
    }
  }

  _blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(String(reader.result).split(',')[1] || '');
      reader.onerror   = () => reject(reader.error || new Error('FileReader error'));
      reader.readAsDataURL(blob);
    });
  }

  // ── 내부 ────────────────────────────────────────────────────────────────────

  _markMicReleased() {
    if (!this._micOpen) return;
    this._micOpen = false;
    this._micReleasedAt = performance.now();
    this._releaseWaiters.splice(0).forEach(fn => fn());
  }

  // 인식이 닫히고 헤드셋이 출력 쪽으로 넘어간 뒤에 풀린다
  async _afterMicReleased() {
    if (this._micOpen) {
      await new Promise((resolve) => {
        this._releaseWaiters.push(resolve);
        setTimeout(resolve, MIC_RELEASE_TIMEOUT_MS);
      });
      this._markMicReleased();
    }
    const left = MIC_SETTLE_MS - (performance.now() - this._micReleasedAt);
    if (left > 0) await new Promise(r => setTimeout(r, left));
  }

  async _acquireHeldMic() {
    if (!this._holdWanted || this._heldStream || !navigator.mediaDevices?.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // 기다리는 사이 Default 로 돌아갔으면 바로 놓는다
      if (this._holdWanted && !this._heldStream) this._heldStream = stream;
      else stream.getTracks().forEach(t => t.stop());
    } catch (_) {
      // 권한이 없으면 잡지 않고 예전처럼 매번 열고 닫는다. 인식 쪽 오류가 따로 알린다.
    }
  }

  _setState(s) {
    if (this._state === s) return;
    this._state = s;
    this._onState(s);
  }
}

window.VoiceManager = VoiceManager;
