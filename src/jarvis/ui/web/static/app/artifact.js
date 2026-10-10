// 응답 안의 큰 코드블록을 오른쪽 패널로 띄운다.
const $panel    = document.getElementById('artifact-panel');
const $lang     = document.getElementById('artifact-lang');
const $code     = document.getElementById('artifact-code');
const $copyBtn  = document.getElementById('artifact-copy-btn');
const $closeBtn = document.getElementById('artifact-close-btn');

const MIN_LINES = 8;  // 이보다 짧은 코드블록은 패널로 띄우지 않는다
let _raw = '';

export function extractArtifact(text) {
  const re = /```(\w*)\n([\s\S]*?)```/g;
  let best = null, m;
  while ((m = re.exec(text)) !== null) {
    const lang = m[1] || 'text';
    const code = m[2];
    const lines = code.split('\n').filter(l => l.trim()).length;
    if (lines >= MIN_LINES && (!best || code.length > best.code.length)) best = { lang, code };
  }
  return best;
}

export function showArtifact(lang, code) {
  _raw = code;
  $lang.textContent = lang.toUpperCase() || 'CODE';
  $code.textContent = code;
  $panel.classList.add('open');
}

export function hideArtifact() { $panel.classList.remove('open'); }

$closeBtn.addEventListener('click', hideArtifact);
$copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(_raw).then(() => {
    $copyBtn.textContent = 'COPIED!';
    setTimeout(() => { $copyBtn.textContent = 'COPY'; }, 2000);
  });
});
