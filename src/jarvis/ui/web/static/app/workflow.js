// Workflow 화면 — 에이전트 지식 그래프(SVG), 최근 위임, 백그라운드 작업. 서버 문자열은 전부 textContent 로만 넣는다.
// 그래프는 에이전트를 가로로 두고, 그 에이전트만 가진 능력(도구, sub-agent, 위임받는 노드)을 바깥쪽 잎으로,
// 여럿이 함께 쓰는 능력을 에이전트 사이에 쌓아 주인들과 잇는다.
import { apiFetch } from './api.js';
import { onViewOpen, currentView } from './view.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const VIEW_W = 960;
const VIEW_H = 540;
const AGENT_R = 30;
const LEAF_R = 5;
const SUB_R = 8;
const LEAF_DIST = 120;       // 에이전트에서 잎까지
const LEAF_STAGGER = 36;     // 잎이 많으면 번갈아 더 멀리 둬 이름이 겹치지 않게
const SHARED_GAP = 26;       // 공통 능력 사이 세로 간격
const LABEL_MAX = 18;
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
let _caps = [];       // { name, description, approval, agents[] }. 한 에이전트만 가진 것이 먼저
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

// 최상위가 아닌 받는 쪽(sub-agent, focus, orchestrate)과 그 노드를 부른 에이전트. 위임 기록이 없으면 main 의 것
function delegates() {
  const top = new Set(_agents.map((a) => a.id));
  const main = (_agents.find((a) => a.main) || _agents[0] || {}).id;
  const owner = new Map(_subagents.map((id) => [id, main]));
  for (const e of _edgeMap.values()) {
    if (!top.has(e.target) && top.has(e.source)) owner.set(e.target, e.source);
  }
  return owner;
}

function shortLabel(name) {
  const plain = name.replace(/^procedure_/, '');
  return plain.length > LABEL_MAX ? `${plain.slice(0, LABEL_MAX - 1)}…` : plain;
}

// 에이전트는 가로 한 줄. 하나면 가운데
function agentPositions() {
  const n = _agents.length;
  return new Map(_agents.map((a, i) => [a.id, {
    x: n === 1 ? VIEW_W / 2 : VIEW_W * (0.3 + (0.4 * i) / (n - 1)),
    y: VIEW_H / 2,
  }]));
}

// 잎을 에이전트 바깥쪽(그래프 가운데의 반대편)으로 부채꼴로 편다. 에이전트가 가운데면 한 바퀴
function fan(center, count) {
  const dx = center.x - VIEW_W / 2;
  const whole = Math.abs(dx) < 1 && _agents.length === 1;
  const base = Math.abs(dx) < 1 ? -Math.PI / 2 : (dx < 0 ? Math.PI : 0);
  const span = whole ? 2 * Math.PI * (1 - 1 / Math.max(count, 1)) : Math.min(Math.PI * 0.95, 0.3 * Math.max(count - 1, 0));
  return Array.from({ length: count }, (_, k) => {
    const angle = base + (count === 1 ? 0 : span * (k / (count - 1) - 0.5));
    const dist = LEAF_DIST + (count > 6 && k % 2 ? LEAF_STAGGER : 0);
    return { x: center.x + dist * Math.cos(angle), y: center.y + dist * Math.sin(angle), cos: Math.cos(angle) };
  });
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

function labelAt(x, y, text, cos, cls) {
  const anchor = cos < -0.25 ? 'end' : cos > 0.25 ? 'start' : 'middle';
  const dx = anchor === 'end' ? -10 : anchor === 'start' ? 10 : 0;
  const t = svg('text', { x: x + dx, y: y + (anchor === 'middle' ? 16 : 3.5), class: cls, 'text-anchor': anchor });
  t.textContent = text;
  return t;
}

function titled(node, text) {
  const title = svg('title');
  title.textContent = text;
  node.appendChild(title);
  return node;
}

function renderGraph() {
  $graph.replaceChildren();
  $graph.setAttribute('viewBox', `0 0 ${VIEW_W} ${VIEW_H}`);
  const pos = agentPositions();
  const color = new Map(_agents.map((a) => [a.id, a.primary]));
  const linkLayer = svg('g', { class: 'wf-links' });
  const nodeLayer = svg('g', { class: 'wf-nodes' });
  $graph.append(linkLayer, nodeLayer);

  // 잎: 에이전트마다 그 에이전트만 가진 능력과 위임받는 노드
  const owned = new Map(_agents.map((a) => [a.id, []]));
  for (const cap of _caps) if (cap.agents.length === 1 && owned.has(cap.agents[0])) owned.get(cap.agents[0]).push({ cap });
  for (const [id, by] of delegates()) if (owned.has(by)) owned.get(by).push({ sub: id });
  for (const [agentId, leaves] of owned) {
    const center = pos.get(agentId);
    fan(center, leaves.length).forEach((p, k) => {
      const leaf = leaves[k];
      const owners = agentId;
      linkLayer.appendChild(svg('line', { x1: center.x, y1: center.y, x2: p.x, y2: p.y, class: 'wf-cap-link', 'data-owners': owners, style: `--node-color:${color.get(agentId)}` }));
      const g = svg('g', { class: `wf-leaf ${leaf.sub ? 'sub' : ''} ${leaf.cap?.approval ? 'approval' : ''}`, 'data-owners': owners, transform: `translate(${p.x},${p.y})` });
      g.style.setProperty('--node-color', color.get(agentId));
      g.appendChild(svg('circle', { r: leaf.sub ? SUB_R : LEAF_R }));
      g.appendChild(labelAt(0, 0, shortLabel(leaf.sub || leaf.cap.name), p.cos, 'wf-leaf-label'));
      titled(g, leaf.sub ? `${leaf.sub} · 위임받는 에이전트` : `${leaf.cap.name}${leaf.cap.approval ? ' · 승인 필요' : ''}\n${leaf.cap.description || ''}`);
      nodeLayer.appendChild(g);
    });
  }

  // 공통 능력: 주인들 사이 가운데에 세로로 쌓는다. 자리가 모자라면 두 줄로
  const shared = _caps.filter((c) => c.agents.length > 1 && c.agents.every((id) => pos.has(id)));
  const perCol = Math.max(1, Math.floor((VIEW_H - 60) / SHARED_GAP));
  const cols = Math.ceil(shared.length / perCol);
  shared.forEach((cap, i) => {
    const col = Math.floor(i / perCol), row = i % perCol;
    const inCol = Math.min(perCol, shared.length - col * perCol);
    const xs = cap.agents.map((id) => pos.get(id).x);
    const x = xs.reduce((a, b) => a + b, 0) / xs.length + (col - (cols - 1) / 2) * 120;
    const y = VIEW_H / 2 + (row - (inCol - 1) / 2) * SHARED_GAP;
    const owners = cap.agents.join(' ');
    for (const id of cap.agents) {
      const a = pos.get(id);
      linkLayer.appendChild(svg('line', { x1: a.x, y1: a.y, x2: x, y2: y, class: 'wf-cap-link shared', 'data-owners': owners, style: `--node-color:${color.get(id)}` }));
    }
    const g = svg('g', { class: `wf-leaf shared ${cap.approval ? 'approval' : ''}`, 'data-owners': owners, transform: `translate(${x},${y})` });
    g.appendChild(svg('circle', { r: LEAF_R - 1 }));
    const label = svg('text', { x: 9, y: 3.5, class: 'wf-leaf-label', 'text-anchor': 'start' });
    label.textContent = shortLabel(cap.name);
    g.appendChild(label);
    titled(g, `${cap.name} · ${cap.agents.map(nameOf).join(', ')} 공통\n${cap.description || ''}`);
    nodeLayer.appendChild(g);
  });

  // 위임: 최상위 에이전트 사이, 또는 에이전트와 위임받는 잎 사이. 같은 쌍은 하나로 묶는다
  const leafPos = new Map();
  nodeLayer.querySelectorAll('.wf-leaf.sub').forEach((g) => {
    const m = /translate\(([-\d.]+),([-\d.]+)\)/.exec(g.getAttribute('transform'));
    leafPos.set(g.querySelector('text').textContent, { x: +m[1], y: +m[2] });
  });
  const busy = new Set();
  const links = pairs();
  for (const p of links) {
    const a = pos.get(p.source) || leafPos.get(shortLabel(p.source));
    const b = pos.get(p.target) || leafPos.get(shortLabel(p.target));
    if (!a || !b) continue;
    if (p.live) { busy.add(p.source); busy.add(p.target); }
    // 같은 쌍의 반대 방향과 겹치지 않게 휜 곡선. 에이전트 사이 위임은 공통 능력 줄 위로 크게 돈다
    const bend = pos.has(p.source) && pos.has(p.target) ? 0.35 : 0.12;
    const mx = (a.x + b.x) / 2 + (b.y - a.y) * bend, my = (a.y + b.y) / 2 - (b.x - a.x) * bend;
    const cls = ['wf-edge', p.live ? 'live' : '', p.lastOk === false ? 'err' : ''].join(' ').trim();
    const path = svg('path', { d: `M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}`, class: cls, 'marker-end': 'url(#wf-arrow)', 'data-owners': `${p.source} ${p.target}` });
    linkLayer.appendChild(titled(path, `${nameOf(p.source)} → ${nameOf(p.target)} · ${p.count}회`));
    const count = svg('text', { x: mx, y: my, class: 'wf-edge-count', 'text-anchor': 'middle' });
    count.textContent = `×${p.count}`;
    linkLayer.appendChild(count);
  }
  const defs = svg('defs');
  const marker = svg('marker', { id: 'wf-arrow', viewBox: '0 0 10 10', refX: 10 + AGENT_R / 2, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse' });
  marker.appendChild(svg('path', { d: 'M0,0 L10,5 L0,10 z', fill: 'currentColor', class: 'wf-arrow' }));
  defs.appendChild(marker);
  $graph.prepend(defs);

  // 에이전트 허브. 올리면 그 에이전트의 능력만 밝게 남는다
  for (const a of _agents) {
    const p = pos.get(a.id);
    const g = svg('g', { class: `wf-node top ${busy.has(a.id) ? 'busy' : ''}`, 'data-owners': a.id, transform: `translate(${p.x},${p.y})` });
    g.style.setProperty('--node-color', a.primary);
    g.appendChild(svg('circle', { r: AGENT_R }));
    const initial = svg('text', { y: 5, class: 'wf-node-initial' });
    initial.textContent = a.name.replace(/[^A-Za-z0-9가-힣]/g, '').slice(0, 1).toUpperCase() || '•';
    const name = svg('text', { y: AGENT_R + 16 });
    name.textContent = a.name;
    g.append(initial, name);
    const ownCount = (owned.get(a.id) || []).length;
    const sub = svg('text', { y: AGENT_R + 29, class: 'wf-node-sub' });
    sub.textContent = `${a.main ? 'main · ' : ''}고유 ${ownCount}`;
    g.appendChild(sub);
    g.addEventListener('mouseenter', () => spotlight(a.id));
    g.addEventListener('mouseleave', () => spotlight(null));
    nodeLayer.appendChild(g);
  }
  const live = links.filter((p) => p.live).length;
  const own = [...owned.values()].reduce((n, l) => n + l.length, 0);
  $summary.textContent = `${_agents.length} agents · 고유 ${own} · 공통 ${shared.length} · ${live} live`;
}

// 에이전트 하나에 닿은 것만 밝히고 나머지는 흐리게. null 이면 모두 원래대로
function spotlight(agentId) {
  $graph.classList.toggle('spotlight', !!agentId);
  $graph.querySelectorAll('[data-owners]').forEach((node) => {
    node.classList.toggle('lit', !!agentId && node.dataset.owners.split(' ').includes(agentId));
  });
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
      _caps = graph.capabilities || [];
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
