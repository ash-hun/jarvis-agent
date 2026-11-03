// Workflow 화면 — 에이전트 관계 그래프(SVG), 최근 위임, 백그라운드 작업. 서버 문자열은 전부 textContent 로만 넣는다.
import { apiFetch } from './api.js';
import { onViewOpen, currentView } from './view.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const VIEW_W = 640;
const VIEW_H = 440;
const INNER_R = 110;
const OUTER_R = 190;
const NODE_R = 26;
const EDGE_LIST_MAX = 40;
const KIND_LABEL = { ask: '질문', subagent: 'sub-agent', orchestrate: 'orchestrate', focus: 'focus' };

const $graph = document.getElementById('wf-graph');
const $summary = document.getElementById('wf-summary');
const $edges = document.getElementById('wf-edges');
const $edgeCount = document.getElementById('wf-edge-count');
const $jobs = document.getElementById('wf-jobs');
const $jobsEmpty = document.getElementById('wf-jobs-empty');
const $daemon = document.getElementById('wf-daemon');

let _agents = [];
let _subagents = [];
const _edgeMap = new Map();  // edge_id → edge. 서버가 보낸 순서(오래된 것부터)
const _jobMap = new Map();   // job_id → job
let _daemonCfg = null;
let _renderQueued = false;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

function clock(ms) {
  if (!ms) return '—';
  return new Date(ms).toLocaleTimeString('ko-KR', { hour12: false });
}

function duration(edge) {
  if (edge.ended_ms == null) return '진행 중';
  const sec = Math.max(0, (edge.ended_ms - edge.started_ms) / 1000);
  return sec < 60 ? `${sec.toFixed(1)}s` : `${Math.round(sec / 60)}m`;
}

function nameOf(id) {
  const a = _agents.find((x) => x.id === id);
  return a ? a.name : id;
}

// 받는 쪽 노드 id 목록. 최상위가 아닌 받는 쪽(sub-agent, focus, orchestrate)은 바깥 원에 둔다
function outerIds() {
  const top = new Set(_agents.map((a) => a.id));
  const ids = new Set(_subagents);
  for (const e of _edgeMap.values()) {
    if (!top.has(e.target)) ids.add(e.target);
    if (!top.has(e.source)) ids.add(e.source);
  }
  return [...ids].sort();
}

function ring(ids, radius, offset) {
  const cx = VIEW_W / 2, cy = VIEW_H / 2;
  const pos = new Map();
  if (ids.length === 1 && radius === INNER_R) { pos.set(ids[0], { x: cx, y: cy }); return pos; }
  ids.forEach((id, i) => {
    const angle = offset + (2 * Math.PI * i) / Math.max(ids.length, 1);
    pos.set(id, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) });
  });
  return pos;
}

// (부른 쪽, 받는 쪽) 쌍마다 하나로 묶는다. 진행 중이 하나라도 있으면 live, 마지막이 실패면 err
function pairs() {
  const map = new Map();
  for (const e of _edgeMap.values()) {
    const key = `${e.source}→${e.target}`;
    const p = map.get(key) || { source: e.source, target: e.target, count: 0, live: false, lastOk: null };
    p.count += 1;
    if (e.ended_ms == null) p.live = true; else p.lastOk = e.ok;
    map.set(key, p);
  }
  return [...map.values()];
}

function renderGraph() {
  $graph.replaceChildren();
  const inner = ring(_agents.map((a) => a.id), INNER_R, -Math.PI / 2);
  const outer = ring(outerIds(), OUTER_R, -Math.PI / 2 + 0.3);
  const pos = new Map([...inner, ...outer]);
  const busy = new Set();
  const links = pairs();
  for (const p of links) {
    const a = pos.get(p.source), b = pos.get(p.target);
    if (!a || !b) continue;
    if (p.live) { busy.add(p.source); busy.add(p.target); }
    // 같은 쌍의 반대 방향과 겹치지 않게 살짝 휜 곡선
    const mx = (a.x + b.x) / 2 + (b.y - a.y) * 0.12, my = (a.y + b.y) / 2 - (b.x - a.x) * 0.12;
    const cls = ['wf-edge', p.live ? 'live' : '', p.lastOk === false ? 'err' : ''].join(' ').trim();
    const path = svg('path', { d: `M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}`, class: cls, 'marker-end': 'url(#wf-arrow)' });
    const title = svg('title');
    title.textContent = `${nameOf(p.source)} → ${nameOf(p.target)} · ${p.count}회`;
    path.appendChild(title);
    $graph.appendChild(path);
    const label = svg('text', { x: mx, y: my, class: 'wf-edge-count', 'text-anchor': 'middle' });
    label.textContent = `×${p.count}`;
    $graph.appendChild(label);
  }
  const defs = svg('defs');
  const marker = svg('marker', { id: 'wf-arrow', viewBox: '0 0 10 10', refX: 10 + NODE_R / 2, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse' });
  marker.appendChild(svg('path', { d: 'M0,0 L10,5 L0,10 z', fill: 'currentColor', class: 'wf-arrow' }));
  defs.appendChild(marker);
  $graph.prepend(defs);
  for (const [id, p] of pos) {
    const agent = _agents.find((a) => a.id === id);
    const g = svg('g', { class: `wf-node ${agent ? 'top' : 'sub'} ${busy.has(id) ? 'busy' : ''}`, transform: `translate(${p.x},${p.y})` });
    if (agent) g.style.setProperty('--node-color', agent.primary);
    g.appendChild(svg('circle', { r: NODE_R }));
    // 원 안에는 첫 글자, 이름은 원 아래. 긴 이름(focus-analysis)이 원을 덮지 않는다
    const label = agent ? agent.name : id;
    const initial = svg('text', { y: 5, class: 'wf-node-initial' });
    initial.textContent = label.replace(/[^A-Za-z0-9가-힣]/g, '').slice(0, 1).toUpperCase() || '•';
    const name = svg('text', { y: NODE_R + 15 });
    name.textContent = label;
    g.append(initial, name);
    if (agent && agent.main) {
      const sub = svg('text', { y: NODE_R + 28, class: 'wf-node-sub' });
      sub.textContent = 'main';
      g.appendChild(sub);
    }
    $graph.appendChild(g);
  }
  const live = links.filter((p) => p.live).length;
  $summary.textContent = `${_agents.length} agents · ${outer.size} sub · ${live} live`;
}

function renderEdges() {
  const list = [..._edgeMap.values()].slice(-EDGE_LIST_MAX).reverse();
  $edgeCount.textContent = String(_edgeMap.size);
  $edges.replaceChildren(...list.map((e) => {
    const li = el('li', e.ended_ms == null ? 'live' : (e.ok === false ? 'err' : ''));
    const route = el('span', 'wf-route', `${nameOf(e.source)} → ${nameOf(e.target)}`);
    route.appendChild(el('span', 'wf-kind', KIND_LABEL[e.kind] || e.kind));
    li.append(route, el('span', 'wf-label', e.label || '—'),
      el('span', 'wf-meta', `${clock(e.started_ms)} · ${duration(e)}${e.ok === false ? ' · 실패' : ''}`));
    return li;
  }));
}

function jobState(job) {
  if (job.running) return ['실행 중', 'st-run'];
  if (job.enabled === false) return ['꺼짐', 'st-off'];
  if (job.last_ok === false) return ['실패', 'st-err'];
  if (job.last_ok === true) return ['성공', 'st-ok'];
  return ['대기', 'st-off'];
}

function renderJobs() {
  const jobs = [..._jobMap.values()];
  $jobsEmpty.hidden = jobs.length > 0;
  $jobs.replaceChildren(...jobs.map((job) => {
    const tr = el('tr');
    const [state, cls] = jobState(job);
    const name = el('td', '', job.label || job.job_id);
    name.title = job.last_error || job.job_id;
    const next = job.next_run ? new Date(job.next_run).toLocaleString('ko-KR', { hour12: false }) : '—';
    tr.append(name, el('td', cls, state), el('td', '', String(job.runs)), el('td', '', clock(job.last_ended_ms || job.last_started_ms)), el('td', '', next));
    return tr;
  }));
  if (_daemonCfg) {
    const d = _daemonCfg;
    $daemon.textContent = d.enabled ? `성찰 ${d.trigger} · ${d.interval_sec}s` : '성찰 꺼짐';
  }
}

function render() {
  _renderQueued = false;
  if (currentView() !== 'workflow') return;
  renderGraph();
  renderEdges();
  renderJobs();
}

// 이벤트가 몰려도 한 프레임에 한 번만 그린다
function queueRender() {
  if (_renderQueued) return;
  _renderQueued = true;
  requestAnimationFrame(render);
}

export async function loadWorkflow() {
  try {
    const [graph, jobs] = await Promise.all([
      apiFetch('/api/workflow').then((r) => (r.ok ? r.json() : null)),
      apiFetch('/api/jobs').then((r) => (r.ok ? r.json() : null)),
    ]);
    if (graph) {
      _agents = graph.agents || [];
      _subagents = graph.subagents || [];
      _edgeMap.clear();
      for (const e of graph.edges || []) _edgeMap.set(e.edge_id, e);
    }
    if (jobs) {
      _jobMap.clear();
      for (const j of jobs.jobs || []) _jobMap.set(j.job_id, j);
      _daemonCfg = jobs.daemon || null;
    }
  } catch { /* 연결이 끊겼으면 다음에 열 때 다시 받는다 */ }
  queueRender();
}

export function onWorkflowEdge(edge) {
  if (!edge || !edge.edge_id) return;
  // 받은 위임은 맨 뒤로. 같은 id 로 다시 열린 Focus 영역도 최신 자리에 온다
  if (edge.ended_ms == null) _edgeMap.delete(edge.edge_id);
  _edgeMap.set(edge.edge_id, { ...(_edgeMap.get(edge.edge_id) || {}), ...edge });
  queueRender();
}

export function onJobChanged(job) {
  if (!job || !job.job_id) return;
  // 스케줄 목록에서 온 enabled, next_run 은 실행 기록에 없다. 있던 값을 지킨다
  _jobMap.set(job.job_id, { ...(_jobMap.get(job.job_id) || {}), ...job });
  queueRender();
}

onViewOpen('workflow', loadWorkflow);
