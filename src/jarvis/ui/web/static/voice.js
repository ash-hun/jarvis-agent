'use strict';

// ── VoiceManager — Web Speech API stubs ─────────────────────────────────────
class VoiceManager {
  constructor(onTranscript) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.recognition = SR ? new SR() : null;
    this.synthesis   = window.speechSynthesis || null;
    this.listening   = false;

    if (this.recognition) {
      this.recognition.lang       = 'ko-KR';
      this.recognition.continuous = false;
      this.recognition.interimResults = false;

      this.recognition.onresult = (e) => {
        const transcript = e.results[0][0].transcript;
        onTranscript(transcript);
      };

      this.recognition.onend = () => {
        this.listening = false;
        document.getElementById('mic-btn').classList.remove('listening');
      };

      this.recognition.onerror = () => {
        this.listening = false;
        document.getElementById('mic-btn').classList.remove('listening');
      };
    }
  }

  get supported() { return !!this.recognition; }

  toggle() {
    if (!this.recognition) return false;
    if (this.listening) {
      this.recognition.stop();
    } else {
      this.recognition.start();
      this.listening = true;
      document.getElementById('mic-btn').classList.add('listening');
    }
    return true;
  }

  speak(text, lang = 'ko-KR') {
    if (!this.synthesis) return;
    this.synthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang;
    this.synthesis.speak(u);
  }
}

window.VoiceManager = VoiceManager;
