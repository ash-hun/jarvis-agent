'use strict';

class VoiceManager {
  constructor(onTranscript) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.recognition = SR ? new SR() : null;
    this.synthesis   = window.speechSynthesis || null;
    this.listening   = false;

    if (this.recognition) {
      this.recognition.lang            = 'ko-KR';
      this.recognition.continuous      = false;
      this.recognition.interimResults  = false;

      this.recognition.onresult = (e) => {
        onTranscript(e.results[0][0].transcript);
      };
      this.recognition.onend = () => {
        this.listening = false;
      };
      this.recognition.onerror = () => {
        this.listening = false;
      };
    }
  }

  get supported() { return !!this.recognition; }

  toggle() {
    if (!this.recognition) return false;
    if (this.listening) {
      this.recognition.stop();
      this.listening = false;
    } else {
      this.recognition.start();
      this.listening = true;
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
