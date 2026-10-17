// 웨이크워드 캡처 AudioWorklet: 16kHz 컨텍스트의 마이크 입력을 int16 1280 샘플(80ms) 묶음으로 메인 스레드에 넘긴다.
const FRAME_SAMPLES = 1280;

class WakeCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this._frame = new Int16Array(FRAME_SAMPLES);
    this._filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      const s = Math.max(-1, Math.min(1, channel[i]));
      this._frame[this._filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this._filled === FRAME_SAMPLES) {
        this.port.postMessage(this._frame.buffer, [this._frame.buffer]);
        this._frame = new Int16Array(FRAME_SAMPLES);
        this._filled = 0;
      }
    }
    return true;
  }
}

registerProcessor('wake-capture', WakeCapture);
