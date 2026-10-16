// 외부 의존 없는 마크다운 렌더 — h1-h4, p, ul/ol/li, pre/code, strong, em, hr.
const _codeStore = {};  // uid → raw code text (copy 버튼용)

export function escapeHtml(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function inlineParse(text) {
  let s = escapeHtml(text);
  s = s.replace(/\*\*(.+?)\*\*/g,  '<strong>$1</strong>');
  s = s.replace(/__(.+?)__/g,       '<strong>$1</strong>');
  s = s.replace(/\*(.+?)\*/g,       '<em>$1</em>');
  s = s.replace(/`([^`]+)`/g,       '<code class="inline-code">$1</code>');
  return s;
}

export function renderMarkdown(src) {
  const lines = src.split('\n');
  let out = '', i = 0, listType = null;

  const closeList = () => { if (listType) { out += `</${listType}>`; listType = null; } };

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.startsWith('```')) {
      closeList();
      const lang = line.slice(3).trim() || 'text';
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) { codeLines.push(lines[i]); i++; }
      const rawCode = codeLines.join('\n');
      const uid = Math.random().toString(36).slice(2, 9);
      _codeStore[uid] = rawCode;
      out += `<div class="code-block">` +
        `<div class="code-head">` +
        `<span class="code-lang">${escapeHtml(lang)}</span>` +
        `<button class="copy-btn" data-uid="${uid}">COPY</button>` +
        `</div>` +
        `<pre><code class="language-${escapeHtml(lang)}">${escapeHtml(rawCode)}</code></pre>` +
        `</div>`;
      i++; continue;
    }

    if (line.trim() === '')    { closeList(); out += '<br>'; i++; continue; }
    if (/^---+$/.test(line.trim())) { closeList(); out += '<hr>'; i++; continue; }

    const h4 = line.match(/^#### (.+)/); if (h4) { closeList(); out += `<h4>${inlineParse(h4[1])}</h4>`; i++; continue; }
    const h3 = line.match(/^### (.+)/); if (h3) { closeList(); out += `<h3>${inlineParse(h3[1])}</h3>`; i++; continue; }
    const h2 = line.match(/^## (.+)/);  if (h2) { closeList(); out += `<h2>${inlineParse(h2[1])}</h2>`; i++; continue; }
    const h1 = line.match(/^# (.+)/);   if (h1) { closeList(); out += `<h1>${inlineParse(h1[1])}</h1>`; i++; continue; }

    const ul = line.match(/^[-*+] (.+)/);
    if (ul) { if (listType !== 'ul') { closeList(); out += '<ul>'; listType = 'ul'; } out += `<li>${inlineParse(ul[1])}</li>`; i++; continue; }

    const ol = line.match(/^\d+[.)]\s+(.+)/);
    if (ol) { if (listType !== 'ol') { closeList(); out += '<ol>'; listType = 'ol'; } out += `<li>${inlineParse(ol[1])}</li>`; i++; continue; }

    closeList();
    out += `<p>${inlineParse(line)}</p>`;
    i++;
  }
  closeList();
  return out;
}

export function attachCopyBtns(container) {
  container.querySelectorAll('.copy-btn[data-uid]').forEach(btn => {
    btn.addEventListener('click', () => {
      const code = _codeStore[btn.dataset.uid] || '';
      navigator.clipboard.writeText(code).then(() => {
        btn.textContent = 'COPIED!';
        setTimeout(() => { btn.textContent = 'COPY'; }, 2000);
      }).catch(() => {
        const pre = btn.closest('.code-block')?.querySelector('pre');
        if (pre) {
          const r = document.createRange();
          r.selectNode(pre);
          window.getSelection().removeAllRanges();
          window.getSelection().addRange(r);
        }
      });
    });
  });
}
