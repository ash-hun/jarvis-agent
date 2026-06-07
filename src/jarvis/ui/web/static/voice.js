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
 *   onTranscript(text)        — STT 결과 콜백
 *   onStateChange(state)      — 상태 변경 콜백 ('idle'|'listening'|'processing'|'speaking')
 *   onError(msg)              — 에러 콜백
 *   onAudioCaptured(b64,mime) — 서버 STT 모드에서 녹음된 오디오를 백엔드로 보낼 때 호출
 *   lang                      — STT 언어 (기본 'ko-KR')
 *
 * STT 모드:
 *   'browser' (기본) — Web Speech API가 브라우저에서 인식
 *   'server'         — MediaRecorder로 녹음 → onAudioCaptured로 백엔드 전송 → receiveTranscript로 결과 수신
 */
class VoiceManager {
  constructor({ onTranscript, onStateChange, onError, onAudioCaptured, lang = 'ko-KR' } = {}) {
    this._state         = 'idle';
    this._onTranscript  = onTranscript    || (() => {});
    this._onState       = onStateChange   || (() => {});
    this._onError       = onError         || (() => {});
    this._onAudioCaptured = onAudioCaptured || (() => {});
    this._lang          = lang;
    this._audioCtx      = null;

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

      this._recognition.onresult = (e) => {
        const results    = Array.from(e.results);
        const transcript = results.map(r => r[0].transcript).join('');
        if (results[results.length - 1].isFinal) {
          this._setState('processing');
          this._onTranscript(transcript);
        }
      };

      this._recognition.onend = () => {
        if (this._state === 'listening') this._setState('idle');
      };

      this._recognition.onerror = (e) => {
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
    try {
      this._recognition.start();
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

  /** 서버 STT 결과(전사 텍스트)를 수신해 onTranscript로 전달한다. */
  receiveTranscript(text) {
    if (!text || !text.trim()) { this._setState('idle'); return; }
    this._onTranscript(text);
  }

  /** 에이전트 응답 처리 중 상태 표시용 */
  setProcessing() { this._setState('processing'); }
  setIdle()       { this._setState('idle'); }

  /**
   * 백엔드에서 받은 base64 WAV 오디오를 재생한다.
   * @param {string} base64Data  — base64 인코딩 WAV
   * @param {string} mimeType    — 'audio/wav' 등
   * @returns {Promise<void>}
   */
  async playAudioBase64(base64Data, mimeType = 'audio/wav') {
    this._setState('speaking');
    try {
      if (!this._audioCtx || this._audioCtx.state === 'closed') {
        this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      // Suspended context (autoplay policy) 해제
      if (this._audioCtx.state === 'suspended') await this._audioCtx.resume();

      const bytes  = Uint8Array.from(atob(base64Data), c => c.charCodeAt(0));
      const buffer = await this._audioCtx.decodeAudioData(bytes.buffer.slice(0));
      const source = this._audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(this._audioCtx.destination);
      source.onended = () => this._setState('idle');
      source.start(0);
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
  speakBrowser(text, lang = this._lang) {
    if (!window.speechSynthesis) { this._setState('idle'); return; }
    this._setState('speaking');
    const u  = new SpeechSynthesisUtterance(text);
    u.lang   = lang;
    u.rate   = 1.0;
    u.onend  = () => this._setState('idle');
    u.onerror = () => this._setState('idle');
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
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

  _setState(s) {
    if (this._state === s) return;
    this._state = s;
    this._onState(s);
  }
}

window.VoiceManager = VoiceManager;
