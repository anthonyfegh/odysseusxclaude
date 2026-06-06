// workspace.js — the Agent Workspace console. A global view of every agent and
// what it's doing: a live timeline of each task run (the agent's thinking, tool
// calls and output streaming in real time, or replayed once finished), a browser
// of the agent's on-disk sandbox folder (data/agents/<id>/), and the artifacts it
// has produced (documents, generated images, research reports).
//
// Backend: task runs stream via /api/tasks/runs/{id}/live (SSE) and persist to
// /steps; artifacts via /api/agents/{id}/{files,documents,images,research}. All
// model calls still route through the configured sidecar — this is read-only.

import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';
import markdownModule from './markdown.js';

const API = window.location.origin;
const esc = (s) => uiModule.esc(String(s ?? ''));

const PALETTE = ['#e2504a', '#4aa3e2', '#4ab87a', '#d9a23b', '#9b6cd9', '#3bb0c0', '#d96aa8', '#7a8aa0'];
function _colorFor(agent) {
  if (agent && agent.color) return agent.color;
  const s = (agent && (agent.name || agent.id)) || '?';
  let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
const _initial = (a) => ((a && a.name) || '?').trim().charAt(0).toUpperCase() || '?';

function _reltime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso), s = (Date.now() - d.getTime()) / 1000;
    if (s < 0) return 'just now';
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    if (s < 604800) return Math.floor(s / 86400) + 'd ago';
    return d.toLocaleDateString();
  } catch { return ''; }
}
function _fmtBytes(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}
const _IMG_RE = /\.(png|jpe?g|gif|webp|svg|bmp|avif)$/i;

// "All agents" overview — a pseudo-selection in the rail that shows a combined
// activity feed across every agent (the global Activity view).
const ALL = '__all__';
const _ALL_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>';
function _anyActive() { return Object.values(_activeByAgent).some(v => v > 0); }

function _ensureStyles() {
  if (document.getElementById('workspace-styles')) return;
  const s = document.createElement('style');
  s.id = 'workspace-styles';
  s.textContent = `
    #workspace-modal .modal-body{padding:0;}
    .ws-body{display:flex;height:min(680px,84vh);min-height:0;}
    .ws-rail{flex:0 0 220px;border-right:1px solid var(--border);overflow-y:auto;padding:10px 8px;display:flex;flex-direction:column;gap:4px;}
    .ws-rail-title{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;opacity:0.6;padding:4px 8px 6px;margin:0;}
    .ws-rail-row{display:flex;align-items:center;gap:9px;padding:8px;border-radius:8px;cursor:pointer;font-size:13px;border:1px solid transparent;}
    .ws-rail-row:hover{background:var(--panel);}
    .ws-rail-row.on{background:var(--panel);border-color:var(--red);}
    .ws-rail-av{width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;color:#fff;flex-shrink:0;position:relative;}
    .ws-rail-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .ws-rail-av svg{display:block;}
    .ws-rail-div{height:1px;background:var(--border);margin:5px 6px 7px;}
    .ws-pulse{width:8px;height:8px;border-radius:50%;background:#4ab87a;flex-shrink:0;box-shadow:0 0 0 0 rgba(74,184,122,0.6);animation:ws-pulse 1.6s infinite;}
    @keyframes ws-pulse{0%{box-shadow:0 0 0 0 rgba(74,184,122,0.55);}70%{box-shadow:0 0 0 6px rgba(74,184,122,0);}100%{box-shadow:0 0 0 0 rgba(74,184,122,0);}}
    .ws-main{flex:1;min-width:0;display:flex;flex-direction:column;}
    .ws-head{display:flex;align-items:center;gap:10px;padding:12px 16px 8px;}
    .ws-head .ws-rail-av{width:32px;height:32px;font-size:14px;}
    .ws-subtabs{display:flex;gap:4px;border-bottom:1px solid var(--border);padding:0 16px;}
    .ws-subtab{background:none;border:none;border-bottom:2px solid transparent;color:inherit;opacity:0.6;font-size:13px;padding:7px 11px;cursor:pointer;}
    .ws-subtab:hover{opacity:0.85;background:none;border-bottom-color:transparent;}
    .ws-subtab.active:hover{border-bottom-color:var(--red);}
    .ws-subtab.active{opacity:1;border-bottom-color:var(--red);font-weight:600;}
    .ws-pane{flex:1;min-height:0;overflow:auto;padding:14px 16px;}
    .ws-empty{opacity:0.5;padding:28px;text-align:center;font-size:13px;}
    /* run list */
    .ws-run{display:flex;align-items:flex-start;gap:9px;padding:10px 11px;border:1px solid var(--border);border-radius:9px;background:var(--bg);margin-bottom:7px;cursor:pointer;transition:border-color .12s;}
    .ws-run:hover{border-color:var(--red);}
    .ws-run-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0;margin-top:4px;background:#888;}
    .ws-run-dot.s-success,.ws-run-dot.s-completed{background:#4ab87a;}
    .ws-run-dot.s-error,.ws-run-dot.s-failed,.ws-run-dot.s-aborted{background:var(--red);}
    .ws-run-dot.s-running,.ws-run-dot.s-queued{background:#4ab87a;animation:ws-pulse 1.6s infinite;}
    .ws-run-title{font-size:13px;font-weight:500;display:block;}
    .ws-run-meta{font-size:11px;opacity:0.64;margin-top:2px;display:block;}
    .ws-run-badge{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.03em;padding:1px 6px;border-radius:9px;background:#4ab87a;color:#fff;margin-left:6px;}
    .ws-run-agent{display:inline-flex;align-items:center;gap:4px;vertical-align:middle;}
    .ws-run-agent-av{width:14px;height:14px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:8px;font-weight:700;color:#fff;}
    /* timeline */
    .ws-tl-head{display:flex;align-items:center;gap:10px;margin-bottom:12px;}
    .ws-tl{display:flex;flex-direction:column;gap:8px;}
    .ws-tl-think{border-left:2px solid var(--border);padding:2px 0 2px 10px;opacity:0.85;}
    .ws-tl-think summary{cursor:pointer;font-size:11px;opacity:0.6;list-style:none;}
    .ws-tl-think .ws-tl-think-body{font-size:12px;opacity:0.78;white-space:pre-wrap;line-height:1.5;margin-top:5px;}
    .ws-tl-text{font-size:13px;line-height:1.55;}
    .ws-tl-text p{margin:0 0 7px;} .ws-tl-text p:last-child{margin:0;}
    .ws-tl-text code{background:var(--panel);padding:1px 4px;border-radius:4px;font-size:12px;}
    .ws-tl-text pre{background:var(--panel);padding:9px 11px;border-radius:8px;overflow:auto;font-size:12px;}
    .ws-tool{border:1px solid var(--border);border-radius:9px;background:var(--bg);overflow:hidden;}
    .ws-tool-head{display:flex;align-items:center;gap:8px;padding:8px 11px;font-size:12px;}
    .ws-tool-ic{flex-shrink:0;}
    .ws-tool-name{font-weight:600;font-family:ui-monospace,monospace;}
    .ws-tool-cmd{opacity:0.6;font-family:ui-monospace,monospace;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;}
    .ws-tool-status{font-size:10px;opacity:0.6;flex-shrink:0;}
    .ws-tool-out{border-top:1px solid var(--border);}
    .ws-tool-out summary{cursor:pointer;font-size:11px;opacity:0.6;padding:6px 11px;list-style:none;}
    .ws-tool-out pre{margin:0;padding:0 11px 10px;font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:280px;overflow:auto;}
    .ws-round{font-size:10px;text-transform:uppercase;letter-spacing:0.05em;opacity:0.4;margin:4px 0;}
    .ws-note{font-size:11px;opacity:0.6;}
    /* files */
    .ws-crumbs{font-size:12px;opacity:0.7;margin-bottom:10px;display:flex;flex-wrap:wrap;gap:3px;align-items:center;}
    .ws-crumb{cursor:pointer;color:var(--red);background:none;border:none;padding:1px 2px;font-size:12px;border-radius:4px;}
    .ws-crumb:hover{text-decoration:underline;}
    .ws-file{display:flex;align-items:center;gap:10px;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);margin-bottom:6px;cursor:pointer;transition:border-color .12s;}
    .ws-file:hover{border-color:var(--red);}
    .ws-file-ic{flex-shrink:0;width:18px;text-align:center;}
    .ws-file-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;}
    .ws-file-meta{font-size:11px;opacity:0.62;flex-shrink:0;}
    .ws-viewer{border:1px solid var(--border);border-radius:9px;margin-top:10px;}
    .ws-viewer-head{display:flex;align-items:center;justify-content:space-between;padding:8px 11px;border-bottom:1px solid var(--border);font-size:12px;}
    .ws-viewer pre{margin:0;padding:11px;font-size:12px;white-space:pre-wrap;word-break:break-word;max-height:340px;overflow:auto;}
    /* shared: clickable rows are real buttons — neutralize the app's global
       button rules (button{height:32px}, .modal-body button{margin-top:6px}) so
       multi-line cards/rows size to their content. */
    .ws-rail-row,.ws-run,.ws-file,.ws-card,.ws-img,.ws-crumb,.ws-subtab{font-family:inherit;box-sizing:border-box;height:auto;min-height:0;}
    .modal-body .ws-rail-row,.modal-body .ws-run,.modal-body .ws-file,.modal-body .ws-card,.modal-body .ws-img,.modal-body .ws-crumb,.modal-body .ws-subtab{margin-top:0;}
    .ws-rail-row,.ws-run,.ws-file,.ws-card{width:100%;text-align:left;color:inherit;}
    .ws-rail-row:focus-visible,.ws-run:focus-visible,.ws-file:focus-visible,.ws-card:focus-visible,.ws-img:focus-visible,.ws-crumb:focus-visible,.ws-subtab:focus-visible,.ws-lightbox-close:focus-visible,#ws-view-close:focus-visible{outline:2px solid var(--red);outline-offset:2px;}
    /* artifacts */
    .ws-sec-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;opacity:0.62;margin:16px 0 9px;}
    .ws-sec-title:first-child{margin-top:2px;}
    .ws-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:9px;list-style:none;margin:0;padding:0;}
    .ws-cards li{display:flex;}
    .ws-card{display:flex;gap:11px;align-items:flex-start;border:1px solid var(--border);border-radius:11px;background:var(--bg);padding:12px 13px;cursor:pointer;transition:border-color .12s,background .12s;}
    .ws-card:hover{border-color:var(--red);background:var(--panel);}
    .ws-ico{flex-shrink:0;width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;color:#fff;}
    .ws-ico svg{width:17px;height:17px;}
    .ws-ico.doc{background:#4aa3e2;} .ws-ico.research{background:#9b6cd9;}
    .ws-card-body{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;}
    .ws-card-top{display:flex;align-items:center;gap:8px;}
    .ws-card-title{font-size:13.5px;font-weight:600;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;}
    .ws-card-tag{flex-shrink:0;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.04em;padding:2px 7px;border-radius:20px;background:var(--panel);border:1px solid var(--border);opacity:0.92;}
    .ws-card-tag.ok{background:rgba(74,184,122,0.16);border-color:rgba(74,184,122,0.42);color:#86d9ab;}
    .ws-card-prev{font-size:12px;line-height:1.45;opacity:0.8;max-height:2.9em;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}
    .ws-card-meta{font-size:11px;opacity:0.64;margin-top:2px;}
    .ws-card-go{flex-shrink:0;align-self:center;opacity:0;color:var(--red);transition:opacity .12s;font-size:16px;line-height:1;}
    .ws-card:hover .ws-card-go,.ws-card:focus-visible .ws-card-go{opacity:0.85;}
    .ws-imgs{display:grid;grid-template-columns:repeat(auto-fill,minmax(116px,1fr));gap:9px;list-style:none;margin:0;padding:0;}
    .ws-imgs li{display:flex;}
    .ws-img{aspect-ratio:1;width:100%;border-radius:10px;overflow:hidden;border:1px solid var(--border);cursor:pointer;background:var(--panel);padding:0;display:block;transition:border-color .12s;}
    .ws-img:hover{border-color:var(--red);}
    .ws-img img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .2s;}
    .ws-img:hover img{transform:scale(1.05);}
    .ws-lightbox{position:fixed;inset:0;z-index:11000;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;padding:30px;cursor:zoom-out;}
    .ws-lightbox img{max-width:92vw;max-height:88vh;border-radius:10px;box-shadow:0 16px 50px rgba(0,0,0,0.6);}
    .ws-lightbox-close{position:fixed;top:18px;right:22px;width:40px;height:40px;border-radius:50%;border:1px solid rgba(255,255,255,0.3);background:rgba(0,0,0,0.45);color:#fff;font-size:17px;cursor:pointer;display:flex;align-items:center;justify-content:center;}`;
  document.head.appendChild(s);
}

let _modal = null, _esc = null, _pollTimer = null, _sse = null;
let _agents = [], _currentAgentId = null, _activeByAgent = {};

function _abortSSE() {
  if (_sse) { try { _sse.abort(); } catch {} _sse = null; }
}

// ---- Global console ----
export async function openWorkspace() {
  _ensureStyles();
  if (_modal) { _modal.remove(); _modal = null; }
  _modal = document.createElement('div');
  _modal.className = 'modal';
  _modal.id = 'workspace-modal';
  _modal.innerHTML = `
    <div class="modal-content" style="width:min(1140px,96vw);height:min(740px,90vh);display:flex;flex-direction:column;background:var(--bg);padding:0;">
      <div class="modal-header" style="padding:12px 16px;">
        <h4 style="display:flex;align-items:center;gap:7px;margin:0;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><rect x="7" y="7" width="10" height="10" rx="1"/></svg>
          Workspace
        </h4>
        <button class="close-btn" id="ws-close">✖</button>
      </div>
      <div class="modal-body">
        <div class="ws-body">
          <div class="ws-rail" id="ws-rail"><div class="ws-rail-title">Agents</div></div>
          <div class="ws-main" id="ws-main"><div class="ws-empty">Select an agent.</div></div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(_modal);
  _modal.classList.remove('hidden');
  _modal.querySelector('#ws-close').addEventListener('click', closeWorkspace);
  _modal.addEventListener('click', (e) => { if (e.target === _modal) closeWorkspace(); });
  const content = _modal.querySelector('.modal-content');
  const header = _modal.querySelector('.modal-header');
  if (content && header) makeWindowDraggable(_modal, { content, header });
  _esc = (e) => { if (e.key === 'Escape') { if (document.querySelector('.ws-lightbox')) return; closeWorkspace(); } };
  document.addEventListener('keydown', _esc);
  await _loadRail();
  _startPolling();
}

export function closeWorkspace() {
  _abortSSE();
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  if (_esc) { document.removeEventListener('keydown', _esc); _esc = null; }
  _closeLightbox();
  if (_modal) { _modal.remove(); _modal = null; }
  _currentAgentId = null;
}

async function _loadRail() {
  const rail = _modal?.querySelector('#ws-rail');
  if (!rail) return;
  try {
    _agents = (await (await fetch(`${API}/api/agents`, { credentials: 'same-origin' })).json()).agents || [];
  } catch { _agents = []; }
  await _refreshActive();
  _renderRail();
  // Open on the combined "All agents" activity overview by default.
  _selectAgent(ALL);
}

function _renderRail() {
  const rail = _modal?.querySelector('#ws-rail');
  if (!rail) return;
  const allOn = _currentAgentId === ALL;
  rail.innerHTML = '<h2 class="ws-rail-title">Agents</h2>'
    + `<button class="ws-rail-row ws-rail-all${allOn ? ' on' : ''}" data-id="${ALL}"${allOn ? ' aria-current="true"' : ''}>
        <span class="ws-rail-av" style="background:#6b6b68;" aria-hidden="true">${_ALL_ICON}</span>
        <span class="ws-rail-name">All agents</span>
        ${_anyActive() ? '<span class="ws-pulse" role="img" aria-label="Running now" title="Running now"></span>' : ''}
      </button>`
    + (_agents.length ? '<div class="ws-rail-div" aria-hidden="true"></div>' : '')
    + _agents.map(a => `
    <button class="ws-rail-row${a.id === _currentAgentId ? ' on' : ''}" data-id="${esc(a.id)}"${a.id === _currentAgentId ? ' aria-current="true"' : ''}>
      <span class="ws-rail-av" style="background:${_colorFor(a)};" aria-hidden="true">${esc(_initial(a))}</span>
      <span class="ws-rail-name">${esc(a.name)}</span>
      ${(_activeByAgent[a.id] || 0) > 0 ? '<span class="ws-pulse" role="img" aria-label="Running now" title="Running now"></span>' : ''}
    </button>`).join('');
  rail.querySelectorAll('.ws-rail-row').forEach(row =>
    row.addEventListener('click', () => _selectAgent(row.dataset.id)));
}

async function _refreshActive() {
  _activeByAgent = {};
  try {
    const d = await (await fetch(`${API}/api/tasks/runs/active`, { credentials: 'same-origin' })).json();
    for (const r of (d.runs || [])) {
      if (r.crew_member_id) _activeByAgent[r.crew_member_id] = (_activeByAgent[r.crew_member_id] || 0) + 1;
    }
  } catch {}
}

function _startPolling() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    if (!_modal) return;
    const before = JSON.stringify(_activeByAgent);
    await _refreshActive();
    if (JSON.stringify(_activeByAgent) !== before) _renderRail();
  }, 5000);
}

function _selectAgent(id) {
  _abortSSE();
  _currentAgentId = id;
  _renderRail();
  const main = _modal?.querySelector('#ws-main');
  if (!main) return;
  if (id === ALL) { mountAllActivity(main); return; }
  const agent = _agents.find(a => a.id === id);
  if (agent) mountAgentWorkspace(main, agent);
}

// ---- Per-agent workspace (reused by the agent dashboard's Workspace tab) ----
export function mountAgentWorkspace(container, agent) {
  _ensureStyles();
  container.innerHTML = `
    <div class="ws-head">
      <span class="ws-rail-av" style="background:${_colorFor(agent)};">${esc(_initial(agent))}</span>
      <div style="min-width:0;">
        <div style="font-size:15px;font-weight:600;">${esc(agent.name)}</div>
        <div style="font-size:12px;opacity:0.6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(agent.description || '')}</div>
      </div>
    </div>
    <div class="ws-subtabs" role="tablist" aria-label="Agent workspace sections">
      <button class="ws-subtab active" data-t="activity" role="tab" aria-selected="true">Live activity</button>
      <button class="ws-subtab" data-t="files" role="tab" aria-selected="false">Files</button>
      <button class="ws-subtab" data-t="artifacts" role="tab" aria-selected="false">Artifacts</button>
    </div>
    <div class="ws-pane" id="ws-pane" role="tabpanel" tabindex="0"></div>`;
  const pane = container.querySelector('#ws-pane');
  const tabs = container.querySelectorAll('.ws-subtab');
  const show = (t) => {
    _abortSSE();
    tabs.forEach(b => { const on = b.dataset.t === t; b.classList.toggle('active', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); });
    if (t === 'activity') _wsActivity(pane, agent);
    else if (t === 'files') _wsFiles(pane, agent, '');
    else if (t === 'artifacts') _wsArtifacts(pane, agent);
  };
  tabs.forEach(b => b.addEventListener('click', () => show(b.dataset.t)));
  show('activity');
}

// ---- All agents: combined activity feed across every agent ----
function mountAllActivity(container) {
  _ensureStyles();
  container.innerHTML = `
    <div class="ws-head">
      <span class="ws-rail-av" style="background:#6b6b68;" aria-hidden="true">${_ALL_ICON}</span>
      <div style="min-width:0;">
        <div style="font-size:15px;font-weight:600;">All agents</div>
        <div style="font-size:12px;opacity:0.6;">Recent activity across every agent</div>
      </div>
    </div>
    <div class="ws-pane" id="ws-pane" tabindex="0"></div>`;
  _wsAllActivity(container.querySelector('#ws-pane'));
}

async function _wsAllActivity(pane) {
  pane.innerHTML = '<div class="ws-empty">Loading activity…</div>';
  let runs = [], activeIds = new Set();
  try {
    // One recent-runs fetch per agent (the endpoint scopes by crew_member_id),
    // tagged with its agent, plus the global active list to mark live runs.
    const lists = await Promise.all(_agents.map(a =>
      fetch(`${API}/api/tasks/runs/recent?crew_member_id=${encodeURIComponent(a.id)}&limit=30`, { credentials: 'same-origin' })
        .then(x => x.json()).then(d => (d.runs || []).map(r => ({ ...r, _agent: a }))).catch(() => [])
    ));
    runs = lists.flat();
    const act = await fetch(`${API}/api/tasks/runs/active`, { credentials: 'same-origin' }).then(x => x.json()).catch(() => ({ runs: [] }));
    activeIds = new Set((act.runs || []).map(r => r.id));
    for (const ar of (act.runs || [])) {
      if (!runs.find(r => r.id === ar.id)) {
        runs.push({ ...ar, _agent: _agents.find(a => a.id === ar.crew_member_id) });
      }
    }
  } catch { pane.innerHTML = '<div class="ws-empty">Couldn\'t load activity.</div>'; return; }

  if (!runs.length) {
    pane.innerHTML = '<div class="ws-empty">No agent activity yet. Assign an agent a task to see it here.</div>';
    return;
  }
  runs.sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
  pane.innerHTML = runs.map(run => {
    const a = run._agent;
    const live = activeIds.has(run.id) || run.status === 'running' || run.status === 'queued';
    const agentChip = a
      ? `<span class="ws-run-agent"><span class="ws-run-agent-av" style="background:${_colorFor(a)};" aria-hidden="true">${esc(_initial(a))}</span>${esc(a.name)}</span> · `
      : '';
    return `
      <button class="ws-run" data-id="${esc(run.id)}" data-live="${live ? '1' : '0'}" aria-label="${esc((a ? a.name + ': ' : '') + (run.task_name || 'Task run') + ', ' + (run.status || ''))}">
        <span class="ws-run-dot s-${esc(run.status || '')}" aria-hidden="true"></span>
        <span style="flex:1;min-width:0;">
          <span class="ws-run-title">${esc(run.task_name || 'Task run')}${live ? '<span class="ws-run-badge">live</span>' : ''}</span>
          <span class="ws-run-meta">${agentChip}${esc(run.status || '')} · ${esc(_reltime(run.started_at))}</span>
        </span>
      </button>`;
  }).join('');
  pane.querySelectorAll('.ws-run').forEach(row => {
    const run = runs.find(r => r.id === row.dataset.id);
    row.addEventListener('click', () => _wsOpenRun(pane, run, row.dataset.live === '1', () => _wsAllActivity(pane)));
  });
}

// ---- Live activity: list of runs → timeline ----
async function _wsActivity(pane, agent) {
  pane.innerHTML = '<div class="ws-empty">Loading runs…</div>';
  let active = [], recent = [];
  try {
    const [a, r] = await Promise.all([
      fetch(`${API}/api/tasks/runs/active?crew_member_id=${encodeURIComponent(agent.id)}`, { credentials: 'same-origin' }).then(x => x.json()),
      fetch(`${API}/api/tasks/runs/recent?crew_member_id=${encodeURIComponent(agent.id)}&limit=60`, { credentials: 'same-origin' }).then(x => x.json()),
    ]);
    active = a.runs || []; recent = r.runs || [];
  } catch { pane.innerHTML = '<div class="ws-empty">Couldn\'t load runs.</div>'; return; }

  const activeIds = new Set(active.map(r => r.id));
  const merged = [...active, ...recent.filter(r => !activeIds.has(r.id))];
  if (!merged.length) {
    pane.innerHTML = '<div class="ws-empty">No runs yet. Assign this agent a task to see it work here.</div>';
    return;
  }
  pane.innerHTML = merged.map(run => {
    const live = activeIds.has(run.id) || run.status === 'running' || run.status === 'queued';
    return `
      <button class="ws-run" data-id="${esc(run.id)}" data-live="${live ? '1' : '0'}">
        <span class="ws-run-dot s-${esc(run.status || '')}" aria-hidden="true"></span>
        <span style="flex:1;min-width:0;">
          <span class="ws-run-title">${esc(run.task_name || 'Task run')}${live ? '<span class="ws-run-badge">live</span>' : ''}</span>
          <span class="ws-run-meta">${esc(run.status || '')} · ${esc(_reltime(run.started_at))}${run.model ? ' · ' + esc((run.model || '').split('/').pop()) : ''}</span>
        </span>
      </button>`;
  }).join('');
  pane.querySelectorAll('.ws-run').forEach(row => {
    const run = merged.find(r => r.id === row.dataset.id);
    row.addEventListener('click', () => _wsOpenRun(pane, run, row.dataset.live === '1', () => _wsActivity(pane, agent)));
  });
}

async function _wsOpenRun(pane, run, live, onBack) {
  _abortSSE();
  pane.innerHTML = `
    <div class="ws-tl-head">
      <button class="agent-act" id="ws-tl-back" style="font-size:11px;padding:5px 12px;border:1px solid var(--border);border-radius:7px;background:var(--panel);color:inherit;cursor:pointer;">← Runs</button>
      <strong style="font-size:14px;">${esc(run.task_name || 'Task run')}</strong>
      <span id="ws-tl-status" class="ws-note"></span>
    </div>
    <div class="ws-tl" id="ws-tl"></div>`;
  pane.querySelector('#ws-tl-back').addEventListener('click', () => { _abortSSE(); onBack(); });
  const tl = pane.querySelector('#ws-tl');
  const statusEl = pane.querySelector('#ws-tl-status');
  const st = { pendingTool: null };

  const finishWith = (label) => { if (statusEl) statusEl.textContent = label; };

  if (live) {
    finishWith('● streaming live…');
    // Prefer the live SSE; if the buffer is already gone it closes immediately
    // and we fall back to the persisted steps.
    let gotAny = false;
    await _streamRun(run.id,
      (step) => { gotAny = true; _appendStepEl(tl, step, st); tl.scrollTop = tl.scrollHeight; },
      async () => {
        if (!gotAny) { await _replayRun(tl, run, st); }
        finishWith('done');
      });
  } else {
    finishWith('replay');
    await _replayRun(tl, run, st);
  }
}

async function _replayRun(tl, run, st) {
  try {
    const d = await (await fetch(`${API}/api/tasks/runs/${encodeURIComponent(run.id)}/steps`, { credentials: 'same-origin' })).json();
    const steps = d.steps || [];
    if (!steps.length) {
      tl.innerHTML = `<div class="ws-tl-text">${markdownModule.mdToHtml(d.result || run.result || '_No recorded steps for this run._')}</div>`;
      return;
    }
    for (const step of steps) _appendStepEl(tl, step, st);
  } catch {
    tl.innerHTML = '<div class="ws-empty">Couldn\'t load this run.</div>';
  }
}

// Convert a raw live SSE frame ({delta, type, ...}) into the persisted step
// shape ({k, ...}) so one renderer handles both live and replay.
function _frameToStep(d) {
  if (!d || typeof d !== 'object') return null;
  if ('delta' in d) return { k: d.thinking ? 'thinking' : 'text', text: d.delta };
  const t = d.type;
  if (t === 'tool_start') return { k: 'tool_start', tool: d.tool, command: d.command || '', round: d.round };
  if (t === 'tool_output') return { k: 'tool_output', tool: d.tool, output: d.stdout || d.output || d.result || '', exit_code: d.exit_code, round: d.round };
  if (t === 'agent_step') return { k: 'agent_step', round: d.round };
  if (t === 'web_sources') { const s = d.sources || d.data || []; return { k: 'web_sources', count: Array.isArray(s) ? s.length : 0 }; }
  if (t === 'doc_stream_open' || t === 'doc_update') return { k: 'document', title: d.title || d.name };
  if (t === 'metrics') return { k: 'metrics', data: d.data };
  return null;
}

// Append one step to the timeline, coalescing consecutive thinking/text and
// finalizing a pending tool node when its output arrives.
function _appendStepEl(tl, step, st) {
  if (!step) return;
  const k = step.k;
  if (k === 'thinking' || k === 'text') {
    const cls = k === 'thinking' ? 'ws-tl-think' : 'ws-tl-text';
    let el = tl.lastElementChild;
    if (!(el && el.classList.contains(cls) && el.dataset.coalesce === '1')) {
      el = document.createElement('div');
      el.className = cls;
      el.dataset.coalesce = '1';
      el.dataset.raw = '';
      if (k === 'thinking') el.innerHTML = '<details open><summary>💭 Thinking</summary><div class="ws-tl-think-body"></div></details>';
      tl.appendChild(el);
    }
    el.dataset.raw = (el.dataset.raw || '') + (step.text || '');
    // Setting innerHTML replaces only the element's children, not its own
    // attributes — dataset.raw / dataset.coalesce / className survive.
    if (k === 'thinking') el.querySelector('.ws-tl-think-body').textContent = el.dataset.raw;
    else el.innerHTML = markdownModule.mdToHtml(el.dataset.raw);
    return;
  }
  // Any non-text step ends the current coalescing run.
  Array.from(tl.children).forEach(c => { c.dataset.coalesce = '0'; });

  if (k === 'agent_step') {
    if (step.round && step.round > 1) {
      const d = document.createElement('div');
      d.className = 'ws-round';
      d.textContent = `— step ${step.round} —`;
      tl.appendChild(d);
    }
  } else if (k === 'tool_start') {
    const node = document.createElement('div');
    node.className = 'ws-tool';
    node.innerHTML = `
      <div class="ws-tool-head">
        <span class="ws-tool-ic">▶</span>
        <span class="ws-tool-name">${esc(step.tool || 'tool')}</span>
        <span class="ws-tool-cmd">${esc((step.command || '').split('\n')[0])}</span>
        <span class="ws-tool-status">running…</span>
      </div>`;
    tl.appendChild(node);
    st.pendingTool = node;
  } else if (k === 'tool_output') {
    let node = st.pendingTool;
    if (!node) {
      node = document.createElement('div');
      node.className = 'ws-tool';
      node.innerHTML = `
        <div class="ws-tool-head">
          <span class="ws-tool-ic">●</span>
          <span class="ws-tool-name">${esc(step.tool || 'tool')}</span>
          <span class="ws-tool-cmd"></span>
          <span class="ws-tool-status"></span>
        </div>`;
      tl.appendChild(node);
    }
    st.pendingTool = null;
    const ok = !step.exit_code || step.exit_code === 0;
    node.querySelector('.ws-tool-ic').textContent = ok ? '✓' : '✗';
    node.querySelector('.ws-tool-ic').style.color = ok ? '#4ab87a' : 'var(--red)';
    node.querySelector('.ws-tool-status').textContent = ok ? 'done' : 'failed';
    const out = (step.output || '').toString();
    if (out.trim()) {
      const det = document.createElement('details');
      det.className = 'ws-tool-out';
      det.innerHTML = `<summary>Output</summary><pre></pre>`;
      det.querySelector('pre').textContent = out;
      node.appendChild(det);
    }
  } else if (k === 'web_sources') {
    const d = document.createElement('div');
    d.className = 'ws-note';
    d.textContent = `🔎 found ${step.count || 0} source${step.count === 1 ? '' : 's'}`;
    tl.appendChild(d);
  } else if (k === 'document') {
    const d = document.createElement('div');
    d.className = 'ws-note';
    d.textContent = `📄 wrote document${step.title ? ': ' + step.title : ''}`;
    tl.appendChild(d);
  } else if (k === 'metrics') {
    const m = step.data || {};
    const bits = [];
    if (m.total_tokens || m.tokens) bits.push(`${m.total_tokens || m.tokens} tokens`);
    if (m.rounds) bits.push(`${m.rounds} steps`);
    if (m.elapsed_s || m.duration) bits.push(`${Math.round(m.elapsed_s || m.duration)}s`);
    if (bits.length) {
      const d = document.createElement('div');
      d.className = 'ws-round';
      d.textContent = bits.join(' · ');
      tl.appendChild(d);
    }
  }
}

async function _streamRun(runId, onStep, onDone) {
  _abortSSE();
  _sse = new AbortController();
  const signal = _sse.signal;
  let res;
  try {
    res = await fetch(`${API}/api/tasks/runs/${encodeURIComponent(runId)}/live`, { credentials: 'same-origin', signal });
  } catch { onDone(); return; }
  if (!res.ok || !res.body) { onDone(); return; }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') { onDone(); return; }
        try { const step = _frameToStep(JSON.parse(payload)); if (step) onStep(step); } catch {}
      }
    }
  } catch { /* aborted or network end */ }
  onDone();
}

// ---- Files: browse the agent's sandbox folder ----
async function _wsFiles(pane, agent, path) {
  pane.innerHTML = '<div class="ws-empty">Loading files…</div>';
  let data;
  try {
    data = await (await fetch(`${API}/api/agents/${encodeURIComponent(agent.id)}/files?path=${encodeURIComponent(path || '')}`, { credentials: 'same-origin' })).json();
  } catch { pane.innerHTML = '<div class="ws-empty">Couldn\'t read the workspace folder.</div>'; return; }
  const cur = data.path || '';
  const parts = cur ? cur.split('/') : [];
  const crumbs = [`<button class="ws-crumb" data-p="">workspace</button>`].concat(
    parts.map((seg, i) => `<span aria-hidden="true" style="opacity:0.4;">/</span><button class="ws-crumb" data-p="${esc(parts.slice(0, i + 1).join('/'))}">${esc(seg)}</button>`)
  ).join('');
  const entries = data.entries || [];
  const list = entries.length ? entries.map(e => {
    const ic = e.is_dir ? '📁' : (_IMG_RE.test(e.name) ? '🖼' : '📄');
    const lbl = (e.is_dir ? 'Folder ' : 'File ') + e.name + (e.is_dir ? '' : ', ' + _fmtBytes(e.size));
    return `<button class="ws-file" data-name="${esc(e.name)}" data-dir="${e.is_dir ? '1' : '0'}" aria-label="${esc(lbl)}">
      <span class="ws-file-ic" aria-hidden="true">${ic}</span>
      <span class="ws-file-name">${esc(e.name)}</span>
      <span class="ws-file-meta">${e.is_dir ? '' : _fmtBytes(e.size)}</span>
    </button>`;
  }).join('') : '<div class="ws-empty">This folder is empty. Files the agent writes land here.</div>';

  pane.innerHTML = `<nav class="ws-crumbs" aria-label="Folder path">${crumbs}</nav><div id="ws-file-list">${list}</div><div id="ws-file-viewer"></div>`;
  pane.querySelectorAll('.ws-crumb').forEach(c => c.addEventListener('click', () => _wsFiles(pane, agent, c.dataset.p)));
  pane.querySelectorAll('.ws-file').forEach(row => row.addEventListener('click', () => {
    const child = (cur ? cur + '/' : '') + row.dataset.name;
    if (row.dataset.dir === '1') _wsFiles(pane, agent, child);
    else _wsViewFile(pane.querySelector('#ws-file-viewer'), agent, child, row.dataset.name);
  }));
}

async function _wsViewFile(viewer, agent, path, name) {
  if (!viewer) return;
  viewer.innerHTML = '<div class="ws-note" style="padding:10px;">Loading…</div>';
  let d;
  try {
    d = await (await fetch(`${API}/api/agents/${encodeURIComponent(agent.id)}/files/read?path=${encodeURIComponent(path)}`, { credentials: 'same-origin' })).json();
  } catch { viewer.innerHTML = '<div class="ws-note" style="padding:10px;">Couldn\'t open file.</div>'; return; }
  const body = d.binary
    ? `<div class="ws-note" style="padding:11px;">Binary file — ${_fmtBytes(d.size)}. Not previewable.</div>`
    : `<pre></pre>`;
  viewer.innerHTML = `
    <div class="ws-viewer">
      <div class="ws-viewer-head"><span>${esc(name)} <span class="ws-note">· ${_fmtBytes(d.size)}${d.truncated ? ' · truncated' : ''}</span></span>
        <button id="ws-view-close" aria-label="Close file preview" style="background:none;border:none;color:inherit;opacity:0.6;cursor:pointer;font-size:14px;">✖</button></div>
      ${body}
    </div>`;
  if (!d.binary) viewer.querySelector('pre').textContent = d.content || '';
  viewer.querySelector('#ws-view-close').addEventListener('click', () => { viewer.innerHTML = ''; });
}

// ---- Artifacts: documents, images, research ----
async function _wsArtifacts(pane, agent) {
  pane.innerHTML = '<div class="ws-empty">Loading artifacts…</div>';
  let docs = [], imgs = [], research = [];
  try {
    const [d, i, r] = await Promise.all([
      fetch(`${API}/api/agents/${encodeURIComponent(agent.id)}/documents`, { credentials: 'same-origin' }).then(x => x.json()),
      fetch(`${API}/api/agents/${encodeURIComponent(agent.id)}/images`, { credentials: 'same-origin' }).then(x => x.json()),
      fetch(`${API}/api/agents/${encodeURIComponent(agent.id)}/research`, { credentials: 'same-origin' }).then(x => x.json()),
    ]);
    docs = d.documents || []; imgs = i.images || []; research = r.research || [];
  } catch { pane.innerHTML = '<div class="ws-empty">Couldn\'t load artifacts.</div>'; return; }

  if (!docs.length && !imgs.length && !research.length) {
    pane.innerHTML = '<div class="ws-empty">Nothing generated yet. Documents, images and research the agent creates appear here.</div>';
    return;
  }
  let html = '';
  if (docs.length) {
    html += '<h3 class="ws-sec-title">Documents</h3><ul class="ws-cards">' + docs.map(d => _cardHtml('doc', {
      sid: d.session_id, title: d.title || 'Untitled', tag: d.language || 'text',
      prev: d.preview || '',
      meta: _reltime(d.updated_at) + (d.session_name ? ' · ' + d.session_name : ''),
      aria: `Document ${d.title || 'Untitled'}${d.session_id ? ', open in chat' : ''}`,
    })).join('') + '</ul>';
  }
  if (research.length) {
    html += '<h3 class="ws-sec-title">Research reports</h3><ul class="ws-cards">' + research.map(r => {
      const st = (r.status || 'done');
      return _cardHtml('research', {
        sid: r.session_id, title: r.query || 'Research report',
        tag: st, tagOk: st.toLowerCase() === 'done',
        prev: r.preview || '',
        meta: _reltime(r.completed_at || r.started_at) + ' · ' + (r.source_count || 0) + ' source' + (r.source_count === 1 ? '' : 's'),
        aria: `Research report ${(r.query || '').slice(0, 80)}${r.session_id ? ', open in chat' : ''}`,
      });
    }).join('') + '</ul>';
  }
  if (imgs.length) {
    html += '<h3 class="ws-sec-title">Images</h3><ul class="ws-imgs">' + imgs.map((im, i) => `
      <li><button class="ws-img" data-url="${esc(im.url)}" aria-label="${esc('Generated image' + (im.prompt ? ': ' + im.prompt.slice(0, 80) : ' ' + (i + 1)) + '. Open larger.')}">
        <img loading="lazy" src="${esc(im.url)}" alt=""></button></li>`).join('') + '</ul>';
  }
  pane.innerHTML = html;

  pane.querySelectorAll('.ws-card').forEach(card => card.addEventListener('click', () => {
    const sid = card.dataset.sid;
    if (sid && window.sessionModule?.selectSession) { closeWorkspace(); window.sessionModule.selectSession(sid); }
  }));
  pane.querySelectorAll('.ws-img').forEach(im => im.addEventListener('click', () => _lightbox(im.dataset.url, im.getAttribute('aria-label'))));
}

// Inline SVG icons (consistent with the app's stroked icon set; emoji avoided
// so screen readers don't announce "microscope"/"page facing up").
const _ART_ICON = {
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h6"/></svg>',
  research: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>',
};

// One artifact card — a real <button> (keyboard-activatable) with a clamped
// 1-line title, a 2-line preview, a meta footer, and a right-aligned status tag.
function _cardHtml(kind, { sid, title, tag, tagOk, prev, meta, aria }) {
  return `<li><button class="ws-card" data-sid="${esc(sid || '')}" aria-label="${esc(aria)}">
    <span class="ws-ico ${kind}" aria-hidden="true">${_ART_ICON[kind] || ''}</span>
    <span class="ws-card-body">
      <span class="ws-card-top">
        <span class="ws-card-title">${esc(title)}</span>
        ${tag ? `<span class="ws-card-tag${tagOk ? ' ok' : ''}">${esc(tag)}</span>` : ''}
      </span>
      ${prev ? `<span class="ws-card-prev">${esc(prev)}</span>` : ''}
      ${meta ? `<span class="ws-card-meta">${esc(meta)}</span>` : ''}
    </span>
    <span class="ws-card-go" aria-hidden="true">→</span>
  </button></li>`;
}

let _lbPrevFocus = null, _lbKey = null;
function _lightbox(url, label) {
  _closeLightbox();
  _lbPrevFocus = document.activeElement;
  const lb = document.createElement('div');
  lb.className = 'ws-lightbox';
  lb.setAttribute('role', 'dialog');
  lb.setAttribute('aria-modal', 'true');
  lb.setAttribute('aria-label', label || 'Image preview');
  lb.innerHTML = `<button class="ws-lightbox-close" aria-label="Close image preview">✕</button><img src="${esc(url)}" alt="${esc(label || '')}">`;
  lb.addEventListener('click', (e) => {
    if (e.target === lb || e.target.classList.contains('ws-lightbox-close')) _closeLightbox();
  });
  document.body.appendChild(lb);
  const closeBtn = lb.querySelector('.ws-lightbox-close');
  closeBtn.focus();
  // Trap focus on the close button + Escape to dismiss. Registered on WINDOW in
  // the capture phase with stopImmediatePropagation so the event never reaches
  // the workspace/dashboard's own document-level Escape handlers (otherwise
  // Escape would also close the modal behind the lightbox).
  _lbKey = (e) => {
    if (e.key === 'Escape') { e.stopImmediatePropagation(); e.preventDefault(); _closeLightbox(); }
    else if (e.key === 'Tab') { e.preventDefault(); closeBtn.focus(); }
  };
  window.addEventListener('keydown', _lbKey, true);
}

function _closeLightbox() {
  document.querySelector('.ws-lightbox')?.remove();
  if (_lbKey) { window.removeEventListener('keydown', _lbKey, true); _lbKey = null; }
  if (_lbPrevFocus && _lbPrevFocus.focus) { try { _lbPrevFocus.focus(); } catch {} }
  _lbPrevFocus = null;
}

const workspaceModule = { openWorkspace, closeWorkspace, mountAgentWorkspace };
export default workspaceModule;
