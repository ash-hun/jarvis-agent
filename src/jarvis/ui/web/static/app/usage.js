// SYSTEM 카드의 토큰·비용 집계.
const $in          = document.getElementById('u-in');
const $out         = document.getElementById('u-out');
const $cr          = document.getElementById('u-cr');
const $cw          = document.getElementById('u-cw');
const $cost        = document.getElementById('u-cost');
const $totalTokens = document.getElementById('usage-total-tokens');
const $sparkline   = document.getElementById('usage-sparkline');

const SPARK_TURNS = 16;
let _model = '—';
const _usage = { input: 0, output: 0, cache_read: 0, cache_write: 0, turns: [] };

// USD / 1M tokens. ponytail: 모델명 부분 일치로 고른 대략값, 정확한 과금이 필요하면 서버가 단가를 내려줘야 한다
function costRate(model) {
  const m = (model || '').toLowerCase();
  if (m.includes('opus'))        return { in: 15,   out: 75  };
  if (m.includes('sonnet'))      return { in: 3,    out: 15  };
  if (m.includes('haiku'))       return { in: 0.8,  out: 4   };
  if (m.includes('gpt-4o-mini')) return { in: 0.15, out: 0.6 };
  if (m.includes('gpt-4o'))      return { in: 5,    out: 15  };
  if (m.includes('gemini'))      return { in: 1.25, out: 5   };
  return { in: 3, out: 15 };
}

function fmtTok(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000)     return (n / 1_000).toFixed(1)     + 'K';
  return String(n);
}

function render() {
  const s = _usage;
  $in.textContent          = fmtTok(s.input);
  $out.textContent         = fmtTok(s.output);
  $cr.textContent          = fmtTok(s.cache_read);
  $cw.textContent          = fmtTok(s.cache_write);
  $totalTokens.textContent = fmtTok(s.input + s.output);

  const rate = costRate(_model);
  $cost.textContent = '$' + ((s.input / 1e6) * rate.in + (s.output / 1e6) * rate.out).toFixed(4);

  const maxOut = Math.max(...s.turns.map(t => t.out), 1);
  $sparkline.innerHTML = s.turns.map(t => {
    const h = Math.max(4, Math.round((t.out / maxOut) * 32));
    return `<div class="spark-bar" style="height:${h}px" title="${t.out} output tokens"></div>`;
  }).join('');
}

export function setModel(model) { _model = model; }

export function updateUsage(usage) {
  _usage.input       += usage.input       || 0;
  _usage.output      += usage.output      || 0;
  _usage.cache_read  += usage.cache_read  || 0;
  _usage.cache_write += usage.cache_write || 0;
  _usage.turns.push({ in: usage.input || 0, out: usage.output || 0 });
  if (_usage.turns.length > SPARK_TURNS) _usage.turns.shift();
  render();
}

export function resetUsage() {
  _usage.input = _usage.output = _usage.cache_read = _usage.cache_write = 0;
  _usage.turns = [];
  render();
}
