// agents.js — the Agent Manager: a roster of agents (CrewMembers) you can
// create, edit, duplicate, delete, and start a chat as. Talking to an agent
// runs the conversation with its persona/model/tools (the backend chat-binding
// seam resolves sessions.crew_member_id). All model calls still route through
// the configured sidecar — new agents leave model/endpoint empty so the
// resolver picks the default (claude -p sidecar).

import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';
import markdownModule from './markdown.js';
import * as spinnerModule from './spinner.js';
import { mountSoul } from './assistant.js';
import { PROMPT_TEMPLATES } from './presets.js';

const API = window.location.origin;
const esc = (s) => uiModule.esc(String(s ?? ''));

// Friendly capability bundles (plain language). Each maps to real tool names.
// A bundle is "on" when all its tools are enabled; saving unions the on-bundles.
const CAP_BUNDLES = [
  { id: 'web',      label: 'Web & knowledge', desc: 'Search the web and recall saved memories', tools: ['web_search', 'web_fetch', 'manage_memory', 'search_chats'] },
  { id: 'email',    label: 'Email',            desc: 'Read, summarize, reply to and organize email', tools: ['list_emails', 'read_email', 'send_email', 'reply_to_email', 'archive_email', 'mark_email_read'] },
  { id: 'calendar', label: 'Calendar & notes', desc: 'Manage your calendar, notes and to-dos', tools: ['manage_calendar', 'manage_notes', 'manage_tasks'] },
  { id: 'docs',     label: 'Documents',        desc: 'Write and edit documents in the editor', tools: ['create_document', 'edit_document', 'update_document', 'suggest_document'] },
  { id: 'images',   label: 'Images',           desc: 'Generate images', tools: ['generate_image'] },
  { id: 'research', label: 'Deep research',    desc: 'Run multi-source research reports', tools: ['trigger_research'] },
  { id: 'code',     label: 'Code & files',     desc: 'Run shell/Python and read/write files (advanced)', tools: ['bash', 'python', 'read_file', 'write_file'] },
];

const PALETTE = ['#e2504a', '#4aa3e2', '#4ab87a', '#d9a23b', '#9b6cd9', '#3bb0c0', '#d96aa8', '#7a8aa0'];
function _colorFor(agent) {
  if (agent.color) return agent.color;
  const s = (agent.name || agent.id || '?');
  let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
const _initial = (a) => (a.name || '?').trim().charAt(0).toUpperCase() || '?';

// Inject the manager's stylesheet once. Uses the app's own theme tokens
// (--red / --border / --bg / --panel) so it matches every other window.
function _ensureStyles() {
  if (document.getElementById('agents-styles')) return;
  const s = document.createElement('style');
  s.id = 'agents-styles';
  s.textContent = `
    #agents-modal .modal-body{padding:14px 16px 16px;}
    .agents-roster{display:flex;flex-direction:column;gap:8px;}
    .agents-empty{opacity:0.5;padding:28px;text-align:center;}
    .agent-card{display:flex;align-items:center;gap:12px;padding:11px 13px;border:1px solid var(--border);border-radius:10px;background:var(--bg);transition:border-color .15s;}
    .agent-card:hover{border-color:var(--red);}
    .agent-avatar{flex-shrink:0;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:16px;color:#fff;}
    .agent-main{flex:1;min-width:0;}
    .agent-name-row{display:flex;align-items:center;gap:8px;}
    .agent-name-row strong{font-size:14px;}
    .agent-badge{font-size:10px;font-weight:600;padding:1px 7px;border-radius:10px;background:var(--red);color:#fff;}
    .agent-role{font-size:12px;opacity:0.65;margin:3px 0 7px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .agent-chips{display:flex;flex-wrap:wrap;gap:5px;}
    .agent-chip{font-size:10px;padding:2px 8px;border-radius:10px;background:var(--panel);border:1px solid var(--border);white-space:nowrap;}
    .agent-chip.dim{opacity:0.55;}
    .agent-actions{display:flex;align-items:center;gap:6px;flex-shrink:0;}
    .agent-act-more{padding:5px 10px;font-weight:700;line-height:1;}
    .agent-act{font-size:11px;padding:5px 12px;border-radius:7px;border:1px solid var(--border);background:var(--panel);color:inherit;cursor:pointer;white-space:nowrap;transition:all .12s;}
    .agent-act:hover{border-color:var(--red);}
    .agent-act.primary{background:var(--red);border-color:var(--red);color:#fff;font-weight:600;}
    .agent-act.primary:hover{filter:brightness(1.1);}
    .agent-act.danger{color:var(--red);}
    .agent-act.danger:hover{background:rgba(198,97,63,0.14);}
    .agent-f{display:flex;flex-direction:column;gap:4px;font-size:12px;font-weight:500;margin-bottom:10px;}
    .agent-f input:not([type=checkbox]),.agent-f textarea{font-weight:400;font-family:inherit;font-size:13px;padding:8px 9px;border:1px solid var(--border);border-radius:7px;background:var(--bg);color:inherit;width:100%;box-sizing:border-box;}
    .agent-f input:focus,.agent-f textarea:focus{outline:none;border-color:var(--red);}
    .agent-caps{display:flex;flex-direction:column;gap:6px;margin-top:4px;}
    .agent-cap-row input{accent-color:var(--red);margin-top:2px;flex-shrink:0;}
    .agent-f .dim{opacity:0.5;font-weight:400;}
    .agent-cap-row{display:flex;gap:9px;align-items:flex-start;font-size:12px;font-weight:400;cursor:pointer;padding:8px 9px;border:1px solid var(--border);border-radius:8px;transition:border-color .12s;}
    .agent-cap-row:hover{border-color:var(--red);}
    .agent-editor-head{display:flex;align-items:center;gap:10px;margin-bottom:12px;}
    .agent-editor-head strong{font-size:14px;}
    /* conversational builder */
    .bld-body{display:flex;height:72vh;max-height:72vh;}
    .bld-chat{flex:1;min-width:0;display:flex;flex-direction:column;border-right:1px solid var(--border);}
    .bld-transcript{flex:1;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:10px;}
    .bld-msg{display:flex;}
    .bld-user{justify-content:flex-end;}
    .bld-ai{justify-content:flex-start;}
    .bld-bubble{max-width:86%;padding:8px 12px;border-radius:13px;font-size:13px;line-height:1.5;}
    .bld-user .bld-bubble{background:var(--red);color:#fff;border-bottom-right-radius:4px;}
    .bld-ai .bld-bubble{background:var(--panel);border:1px solid var(--border);border-bottom-left-radius:4px;}
    .bld-bubble p{margin:0 0 6px;} .bld-bubble p:last-child{margin:0;}
    .bld-bubble code{background:var(--bg);padding:1px 4px;border-radius:4px;font-size:12px;}
    .bld-thinking{display:flex;align-items:center;gap:8px;opacity:0.7;}
    .bld-inputrow{display:flex;gap:8px;padding:10px 12px;border-top:1px solid var(--border);align-items:flex-end;}
    .bld-inputrow textarea{flex:1;resize:none;font-family:inherit;font-size:13px;line-height:1.4;padding:8px 10px;border:1px solid var(--border);border-radius:9px;background:var(--bg);color:inherit;max-height:120px;}
    .bld-inputrow textarea:focus{outline:none;border-color:var(--red);}
    .bld-side{flex:0 0 300px;display:flex;flex-direction:column;padding:14px;gap:12px;overflow-y:auto;}
    .bld-side-label{font-size:11px;text-transform:uppercase;letter-spacing:0.04em;opacity:0.5;}
    .bld-preview{border:1px solid var(--border);border-radius:12px;padding:16px 14px;background:var(--bg);text-align:center;}
    .bld-preview .agent-avatar{margin:0 auto 8px;width:48px;height:48px;font-size:19px;}
    .bld-preview-name{font-size:15px;font-weight:600;}
    .bld-preview-role{font-size:12px;opacity:0.65;margin:3px 0 9px;}
    .bld-persona{font-size:11px;opacity:0.6;margin-top:10px;max-height:96px;overflow:hidden;text-align:left;white-space:pre-wrap;border-top:1px solid var(--border);padding-top:8px;}
    /* active-agent chip + picker */
    #agent-indicator-btn{display:inline-flex;align-items:center;}
    .agent-picker-pop{position:fixed;z-index:10050;background:var(--panel);border:1px solid var(--border);border-radius:11px;padding:6px;min-width:210px;max-height:50vh;overflow-y:auto;box-shadow:0 10px 30px rgba(0,0,0,0.45);}
    .agent-picker-title{font-size:10px;text-transform:uppercase;letter-spacing:0.04em;opacity:0.5;padding:4px 8px 6px;}
    .agent-picker-row{display:flex;align-items:center;gap:9px;padding:7px 8px;border-radius:8px;cursor:pointer;font-size:13px;}
    .agent-picker-row:hover{background:var(--bg);}
    .agent-picker-row.on{background:var(--bg);outline:1px solid var(--red);}
    .agent-picker-row.danger{color:var(--red);}
    .agent-picker-av{width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:#fff;flex-shrink:0;}
    .agent-picker-new{padding:8px;border-radius:8px;cursor:pointer;font-size:12px;opacity:0.7;border-top:1px solid var(--border);margin-top:4px;}
    .agent-picker-new:hover{opacity:1;color:var(--red);}
    /* per-agent dashboard */
    .dash-head{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
    .dash-tabs{display:flex;gap:4px;border-bottom:1px solid var(--border);margin-bottom:10px;}
    .dash-tab{background:none;border:none;border-bottom:2px solid transparent;color:inherit;opacity:0.6;font-size:13px;padding:6px 10px;cursor:pointer;}
    .dash-tab:hover{opacity:0.85;}
    .dash-tab.active{opacity:1;border-bottom-color:var(--red);font-weight:600;}
    .dash-row{display:flex;align-items:flex-start;gap:9px;padding:9px 10px;border:1px solid var(--border);border-radius:9px;background:var(--bg);margin-bottom:7px;}
    .dash-click{cursor:pointer;transition:border-color .12s;}
    .dash-click:hover{border-color:var(--red);}
    .dash-row-title{font-size:13px;font-weight:500;}
    .dash-row-meta{font-size:11px;opacity:0.55;margin-top:2px;}
    .dash-row-result{font-size:11px;opacity:0.7;margin-top:5px;white-space:pre-wrap;max-height:60px;overflow:hidden;}
    .dash-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:5px;background:#888;}
    .dash-dot.dash-success,.dash-dot.dash-completed{background:#4ab87a;}
    .dash-dot.dash-error,.dash-dot.dash-failed{background:var(--red);}
    .dash-dot.dash-running{background:#d9a23b;}`;
  document.head.appendChild(s);
}

let _modal = null;
let _escHandler = null;
let _bModal = null, _bEsc = null, _bid = null, _bDraft = null, _bAgent = null, _bThinkingEl = null;

async function _api(path, opts) {
  const res = await fetch(`${API}/api/agents${path}`, opts);
  let data = {};
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ---- Roster ----
export function openManager() {
  _ensureStyles();
  if (_modal) { _modal.remove(); _modal = null; }
  _modal = document.createElement('div');
  _modal.className = 'modal';
  _modal.id = 'agents-modal';
  _modal.innerHTML = `
    <div class="modal-content" style="width:min(720px,94vw);height:min(560px,86vh);display:flex;flex-direction:column;background:var(--bg);">
      <div class="modal-header">
        <h4 style="display:flex;align-items:center;gap:6px;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          Agents
        </h4>
        <button class="close-btn" id="agents-close">✖</button>
      </div>
      <div class="modal-body" id="agents-body" style="flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:10px;"></div>
    </div>`;
  document.body.appendChild(_modal);
  _modal.classList.remove('hidden');
  _modal.querySelector('#agents-close').addEventListener('click', closeManager);
  _modal.addEventListener('click', (e) => { if (e.target === _modal) closeManager(); });
  // Make the window draggable / dockable like every other window.
  const _content = _modal.querySelector('.modal-content');
  const _header = _modal.querySelector('.modal-header');
  if (_content && _header) makeWindowDraggable(_modal, { content: _content, header: _header });
  // Escape closes, matching the other modals.
  _escHandler = (e) => { if (e.key === 'Escape') closeManager(); };
  document.addEventListener('keydown', _escHandler);
  renderRoster();
}

export function closeManager() {
  if (_escHandler) { document.removeEventListener('keydown', _escHandler); _escHandler = null; }
  if (_modal) { _modal.remove(); _modal = null; }
}

// ---- Conversational builder (chat to create/edit an agent) ----
export async function openBuilder(opts = {}) {
  _ensureStyles();
  closeManager();
  if (_bModal) { _bModal.remove(); _bModal = null; }
  _bAgent = opts.mode === 'edit' ? opts.agent : null;
  _bModal = document.createElement('div');
  _bModal.className = 'modal';
  _bModal.id = 'agent-builder-modal';
  _bModal.innerHTML = `
    <div class="modal-content" style="width:min(940px,96vw);max-height:86vh;display:flex;flex-direction:column;background:var(--bg);padding:0;">
      <div class="modal-header" style="padding:12px 16px;">
        <h4 style="display:flex;align-items:center;gap:6px;margin:0;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
          ${_bAgent ? 'Edit agent' : 'New agent'}
        </h4>
        <button class="close-btn" id="bld-close">✖</button>
      </div>
      <div class="bld-body">
        <div class="bld-chat">
          <div class="bld-transcript" id="bld-transcript"></div>
          <div class="bld-inputrow">
            <textarea id="bld-input" rows="1" placeholder="Describe the agent, or ask for a change…"></textarea>
            <button class="agent-act primary" id="bld-send">Send</button>
          </div>
        </div>
        <div class="bld-side">
          <div class="bld-side-label">Live preview</div>
          <div id="bld-preview"></div>
          <button class="agent-act primary" id="bld-save" style="padding:8px 14px;">Save agent</button>
          <button class="agent-act" id="bld-back">← Back to agents</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(_bModal);
  _bModal.classList.remove('hidden');
  const content = _bModal.querySelector('.modal-content');
  const header = _bModal.querySelector('.modal-header');
  if (content && header) makeWindowDraggable(_bModal, { content, header });
  _bEsc = (e) => { if (e.key === 'Escape') closeBuilder(); };
  document.addEventListener('keydown', _bEsc);
  _bModal.querySelector('#bld-close').addEventListener('click', closeBuilder);
  _bModal.querySelector('#bld-back').addEventListener('click', () => { closeBuilder(); openManager(); });
  _bModal.querySelector('#bld-save').addEventListener('click', _builderSave);
  const input = _bModal.querySelector('#bld-input');
  _bModal.querySelector('#bld-send').addEventListener('click', _builderSend);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _builderSend(); } });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(120, input.scrollHeight) + 'px'; });

  _setThinking(true);
  try {
    const data = await _api('/builder/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed_agent_id: _bAgent ? _bAgent.id : null, seed_template: opts.seedTemplate || null }),
    });
    _bid = data.builder_id; _bDraft = data.draft;
    _setThinking(false);
    _appendBubble('ai', data.reply);
    _renderPreview();
  } catch (e) { _setThinking(false); _appendBubble('ai', 'Could not start the builder: ' + e.message); }
  input.focus();
}

function closeBuilder() {
  if (_bEsc) { document.removeEventListener('keydown', _bEsc); _bEsc = null; }
  if (_bModal) { _bModal.remove(); _bModal = null; }
  _bid = null; _bDraft = null; _bAgent = null; _bThinkingEl = null;
}

function _appendBubble(role, text) {
  const t = _bModal?.querySelector('#bld-transcript');
  if (!t) return;
  const wrap = document.createElement('div');
  wrap.className = 'bld-msg bld-' + role;
  const bub = document.createElement('div');
  bub.className = 'bld-bubble';
  bub.innerHTML = role === 'user' ? esc(text).replace(/\n/g, '<br>') : markdownModule.mdToHtml(text || '');
  wrap.appendChild(bub);
  t.appendChild(wrap);
  t.scrollTop = t.scrollHeight;
}

function _setThinking(on) {
  const t = _bModal?.querySelector('#bld-transcript');
  if (!t) return;
  if (on) {
    if (_bThinkingEl) return;
    _bThinkingEl = document.createElement('div');
    _bThinkingEl.className = 'bld-msg bld-ai';
    _bThinkingEl.innerHTML = '<div class="bld-bubble bld-thinking"><span>Thinking…</span></div>';
    try {
      const sp = spinnerModule.create('', 'clean', 'whirlpool');
      _bThinkingEl._sp = sp;
      _bThinkingEl.querySelector('.bld-bubble').prepend(sp.createElement());
      sp.start();
    } catch (_) {}
    t.appendChild(_bThinkingEl);
    t.scrollTop = t.scrollHeight;
  } else if (_bThinkingEl) {
    try { _bThinkingEl._sp?.stop(); } catch (_) {}
    _bThinkingEl.remove();
    _bThinkingEl = null;
  }
}

async function _builderSend() {
  const input = _bModal?.querySelector('#bld-input');
  const send = _bModal?.querySelector('#bld-send');
  if (!input || !_bid) return;
  const text = input.value.trim();
  if (!text) return;
  input.value = ''; input.style.height = 'auto';
  _appendBubble('user', text);
  if (send) send.disabled = true;
  _setThinking(true);
  try {
    const data = await _api(`/builder/${_bid}/message`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    _bDraft = data.draft;
    _setThinking(false);
    _appendBubble('ai', data.reply);
    _renderPreview();
  } catch (e) { _setThinking(false); _appendBubble('ai', 'Error: ' + e.message); }
  if (send) send.disabled = false;
  input.focus();
}

async function _builderSave() {
  if (!_bid) return;
  const btn = _bModal?.querySelector('#bld-save');
  if (btn) btn.disabled = true;
  try {
    await _api(`/builder/${_bid}/commit`, { method: 'POST' });
    uiModule.showToast(_bAgent ? 'Agent updated' : 'Agent created');
    closeBuilder();
    openManager();
  } catch (e) {
    if (btn) btn.disabled = false;
    uiModule.showError(e.message || 'Save failed');
    _appendBubble('ai', '⚠️ ' + (e.message || 'Save failed'));
  }
}

function _renderPreview() {
  const el = _bModal?.querySelector('#bld-preview');
  if (!el || !_bDraft) return;
  const d = _bDraft;
  const caps = (d.capabilities || []).map(id => (CAP_BUNDLES.find(b => b.id === id) || {}).label).filter(Boolean);
  const chips = caps.length
    ? caps.map(c => `<span class="agent-chip">${esc(c)}</span>`).join('')
    : '<span class="agent-chip dim">All capabilities</span>';
  const ini = (d.name || '?').trim().charAt(0).toUpperCase() || '?';
  el.innerHTML = `
    <div class="bld-preview">
      <div class="agent-avatar" style="background:${_colorFor({ name: d.name || '?' })};">${esc(ini)}</div>
      <div class="bld-preview-name">${esc(d.name || 'Untitled agent')}</div>
      <div class="bld-preview-role">${esc(d.description || 'No role yet')}</div>
      <div class="agent-chips" style="justify-content:center;">${chips}</div>
      ${d.personality ? `<div class="bld-persona">${esc(d.personality)}</div>` : ''}
    </div>`;
}

async function renderRoster() {
  const body = _modal?.querySelector('#agents-body');
  if (!body) return;
  body.innerHTML = '<div style="opacity:0.5;padding:20px;text-align:center;">Loading agents…</div>';
  let agents = [];
  try { agents = (await _api('', {})).agents || []; }
  catch (e) { body.innerHTML = `<div style="opacity:0.6;padding:20px;">Couldn't load agents: ${esc(e.message)}</div>`; return; }

  const newBtn = `<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;">
      <button class="btn" id="agents-new" style="display:flex;align-items:center;gap:6px;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        New agent</button>
      <button class="btn" id="agents-template" style="display:flex;align-items:center;gap:5px;opacity:0.85;">From character ▾</button>
    </div>`;

  const cards = agents.map(a => {
    const tools = a.enabled_tools || [];
    const caps = CAP_BUNDLES.filter(b => b.tools.some(t => tools.includes(t))).map(b => b.label);
    const capChips = (tools.length === 0
      ? '<span class="agent-chip dim">All capabilities</span>'
      : caps.slice(0, 4).map(c => `<span class="agent-chip">${esc(c)}</span>`).join('') +
        (caps.length > 4 ? `<span class="agent-chip dim">+${caps.length - 4}</span>` : ''));
    const modelChip = a.model
      ? `<span class="agent-chip dim">${esc((a.model || '').split('/').pop())}</span>`
      : '<span class="agent-chip dim">default model</span>';
    const desc = esc(a.description || (a.personality || '').slice(0, 100) || 'No description yet');
    return `
      <div class="agent-card" data-id="${esc(a.id)}">
        <div class="agent-avatar" style="background:${_colorFor(a)};">${esc(_initial(a))}</div>
        <div class="agent-main">
          <div class="agent-name-row"><strong>${esc(a.name)}</strong>${a.is_default_assistant ? '<span class="agent-badge">Default</span>' : ''}</div>
          <div class="agent-role">${desc}</div>
          <div class="agent-chips">${modelChip}${capChips}</div>
        </div>
        <div class="agent-actions">
          <button class="agent-act primary" data-act="chat">Chat</button>
          <button class="agent-act" data-act="assign">Assign task</button>
          <button class="agent-act agent-act-more" data-act="more" title="More">⋯</button>
        </div>
      </div>`;
  }).join('');

  body.innerHTML = `
    ${newBtn}
    <div class="agents-roster">
      ${agents.length ? cards : '<div class="agents-empty">No agents yet — create your first one.</div>'}
    </div>`;

  body.querySelector('#agents-new')?.addEventListener('click', () => openBuilder({ mode: 'create' }));
  body.querySelector('#agents-template')?.addEventListener('click', (e) => _openTemplateMenu(e.currentTarget));
  body.querySelectorAll('.agent-card').forEach(card => {
    const id = card.dataset.id;
    const agent = agents.find(x => x.id === id);
    card.querySelectorAll('[data-act]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const act = btn.dataset.act;
        if (act === 'chat') chatWithAgent(agent);
        else if (act === 'assign') _assignTask(agent);
        else if (act === 'more') _cardMenu(btn, agent);
        else if (act === 'edit') openBuilder({ mode: 'edit', agent });
        else if (act === 'dup') _duplicate(agent);
        else if (act === 'del') _delete(agent);
      });
    });
    // Clicking the card body (not an action button) opens its dashboard.
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => renderAgentDashboard(agent));
  });
}

// ---- Create / edit form ----
function openEditor(agent, allAgents) {
  const body = _modal?.querySelector('#agents-body');
  if (!body) return;
  const isNew = !agent;
  agent = agent || { name: '', description: '', personality: '', greeting: '', enabled_tools: [] };
  const tools = agent.enabled_tools || [];
  const bundleOn = (b) => b.tools.some(t => tools.includes(t));

  body.innerHTML = `
    <div class="agent-editor-head">
      <button class="agent-act" id="agents-back">← Back</button>
      <strong>${isNew ? 'New agent' : 'Edit ' + esc(agent.name)}</strong>
    </div>
    <label class="agent-f">Name<input id="ag-name" type="text" value="${esc(agent.name)}" placeholder="e.g. Scout"></label>
    <label class="agent-f">Role <span class="dim">(one line)</span><input id="ag-desc" type="text" value="${esc(agent.description || '')}" placeholder="e.g. Researches topics and takes notes"></label>
    <label class="agent-f">Personality / instructions<textarea id="ag-pers" rows="6" placeholder="Describe how this agent should behave, its tone, and what it should do.">${esc(agent.personality || '')}</textarea></label>
    <label class="agent-f">Greeting <span class="dim">(optional)</span><input id="ag-greet" type="text" value="${esc(agent.greeting || '')}" placeholder="First thing it says"></label>
    <div class="agent-f">Capabilities <span class="dim">(what it can do)</span>
      <div id="ag-caps" class="agent-caps">
        ${CAP_BUNDLES.map(b => `
          <label class="agent-cap-row">
            <input type="checkbox" data-bundle="${b.id}" ${bundleOn(b) ? 'checked' : ''}>
            <span><strong>${esc(b.label)}</strong><br><span style="opacity:0.65;">${esc(b.desc)}</span></span>
          </label>`).join('')}
      </div>
      <div class="dim" style="font-size:11px;margin-top:5px;font-weight:400;">Leave all unchecked to give the agent every capability.</div>
    </div>
    <div class="dim" style="font-size:11px;font-weight:400;margin-bottom:10px;">Uses your default model (Claude via the sidecar).</div>
    <div style="display:flex;gap:8px;">
      <button class="agent-act primary" id="ag-save" style="padding:7px 16px;">${isNew ? 'Create agent' : 'Save'}</button>
      <button class="agent-act" id="ag-cancel">Cancel</button>
    </div>`;

  const back = () => renderRoster();
  body.querySelector('#agents-back').addEventListener('click', back);
  body.querySelector('#ag-cancel').addEventListener('click', back);
  body.querySelector('#ag-save').addEventListener('click', async () => {
    const name = body.querySelector('#ag-name').value.trim();
    if (!name) { uiModule.showToast('Name is required'); return; }
    const selected = [...body.querySelectorAll('#ag-caps input:checked')].map(c => c.dataset.bundle);
    const enabled_tools = [...new Set(selected.flatMap(id => (CAP_BUNDLES.find(b => b.id === id) || {}).tools || []))];
    const payload = {
      name,
      description: body.querySelector('#ag-desc').value.trim(),
      personality: body.querySelector('#ag-pers').value,
      greeting: body.querySelector('#ag-greet').value.trim(),
      enabled_tools,  // [] = all capabilities (backend treats empty as unrestricted)
    };
    try {
      if (isNew) await _api('', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      else await _api(`/${agent.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      uiModule.showToast(isNew ? 'Agent created' : 'Saved');
      renderRoster();
    } catch (e) { uiModule.showError('Save failed: ' + e.message); }
  });
}

async function _duplicate(agent) {
  try { await _api(`/${agent.id}/duplicate`, { method: 'POST' }); uiModule.showToast('Duplicated'); renderRoster(); }
  catch (e) { uiModule.showError('Duplicate failed: ' + e.message); }
}

async function _delete(agent) {
  if (!(await uiModule.styledConfirm(`Delete agent "${agent.name}"? This can't be undone.`, { confirmText: 'Delete', danger: true }))) return;
  try { await _api(`/${agent.id}`, { method: 'DELETE' }); uiModule.showToast('Deleted'); renderRoster(); }
  catch (e) { uiModule.showError('Delete failed: ' + e.message); }
}

// Open the task creator pre-bound to this agent.
function _assignTask(agent) {
  closeManager();
  if (window.tasksModule?.openTasks) window.tasksModule.openTasks(null, 'new', agent.id);
  else uiModule.showError('Tasks unavailable');
}

// ---- Per-agent dashboard (Persona · Tasks · Activity · Chats) ----
function _reltime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso), s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    if (s < 604800) return Math.floor(s / 86400) + 'd ago';
    return d.toLocaleDateString();
  } catch { return ''; }
}

export function renderAgentDashboard(agent) {
  const body = _modal?.querySelector('#agents-body');
  if (!body) return;
  body.innerHTML = `
    <div class="dash-head">
      <button class="agent-act" id="dash-back">← Agents</button>
      <span class="agent-avatar" style="width:30px;height:30px;font-size:13px;background:${_colorFor(agent)};">${esc(_initial(agent))}</span>
      <strong style="font-size:15px;">${esc(agent.name)}</strong>
      <span style="opacity:0.6;font-size:12px;">${esc(agent.description || '')}</span>
    </div>
    <div class="dash-tabs">
      <button class="dash-tab active" data-t="persona">Persona</button>
      <button class="dash-tab" data-t="workspace">Workspace</button>
      <button class="dash-tab" data-t="tasks">Tasks</button>
      <button class="dash-tab" data-t="activity">Activity</button>
      <button class="dash-tab" data-t="chats">Chats</button>
    </div>
    <div id="dash-pane" style="flex:1;min-height:0;overflow:auto;"></div>
    <div id="dash-engine-footer" class="dash-engine-footer"></div>`;
  body.querySelector('#dash-back').addEventListener('click', renderRoster);
  _renderEngineFooter(body, agent);
  const pane = body.querySelector('#dash-pane');
  const tabs = body.querySelectorAll('.dash-tab');
  const show = (t) => {
    tabs.forEach(b => b.classList.toggle('active', b.dataset.t === t));
    if (t === 'persona') _dashPersona(pane, agent);
    else if (t === 'workspace') _dashWorkspace(pane, agent);
    else if (t === 'tasks') _dashTasks(pane, agent);
    else if (t === 'activity') _dashActivity(pane, agent);
    else if (t === 'chats') _dashChats(pane, agent);
  };
  tabs.forEach(b => b.addEventListener('click', () => show(b.dataset.t)));
  show('persona');
}

// The "open this session in a real terminal" command + a "Reset session"
// control for the agent's Claude Code session. Lives at the bottom of the
// per-agent dashboard. Agents run uniformly on the Claude Code engine — there
// is no user-facing engine picker (a backend `engine='legacy'` override just
// shows a hint here).
function _renderEngineFooter(body, agent) {
  const foot = body.querySelector('#dash-engine-footer');
  if (!foot) return;
  const isCC = (agent.engine || 'claude_code') !== 'legacy';
  const sid = agent.claude_session_id;
  const cmd = sid ? `cd data/agents/${agent.id} && claude --resume ${sid}` : '';
  if (!isCC) {
    foot.innerHTML = `<div class="dash-term dash-term-label">This agent runs on the legacy sidecar (backend engine override).</div>`;
    return;
  }
  const term = sid
    ? `<div class="dash-term"><span class="dash-term-label">Open this agent's live session in your terminal (from your odysseus folder):</span>
         <code class="dash-term-cmd">${esc(cmd)}</code>
         <button class="agent-act" id="dash-term-copy">Copy</button></div>`
    : `<div class="dash-term dash-term-label">A terminal command (claude --resume …) appears here after this agent's first message.</div>`;
  foot.innerHTML = `
    <div class="dash-engine-row">
      <button class="agent-act" id="dash-reset-session" title="Archive the current chat (kept searchable) and start a fresh session">Reset session</button>
    </div>
    ${term}`;
  foot.querySelector('#dash-term-copy')?.addEventListener('click', () => {
    try { uiModule.copyToClipboard(cmd); uiModule.showToast('Command copied'); } catch (_) {}
  });
  foot.querySelector('#dash-reset-session')?.addEventListener('click', async () => {
    if (window.styledConfirm && !await window.styledConfirm(
        "Start a fresh session? The current chat is archived (still searchable) and the agent's working memory resets.",
        { confirmText: 'Reset', danger: true })) return;
    try {
      const r = await (await fetch(`${API}/api/agents/${agent.id}/reset_session`, { method: 'POST', credentials: 'same-origin' })).json();
      agent.claude_session_id = null; if (r.new_session) agent.session_id = r.new_session;
      _agentCache = null;
      _renderEngineFooter(body, agent);
      uiModule.showToast('Session reset — past chat archived');
    } catch (err) { uiModule.showError('Reset failed: ' + err.message); }
  });
}

function _dashPersona(pane, agent) {
  // The default assistant keeps its check-ins via the /api/assistant path.
  mountSoul(pane, agent.is_default_assistant ? {} : { agentId: agent.id, onSaved: () => { _agentCache = null; } });
}

function _dashWorkspace(pane, agent) {
  // Live activity + sandbox files + artifacts — the same renderer the global
  // Workspace console uses, scoped to this one agent.
  if (window.workspaceModule?.mountAgentWorkspace) {
    pane.innerHTML = '';
    window.workspaceModule.mountAgentWorkspace(pane, agent);
  } else {
    pane.innerHTML = '<div class="agents-empty">Workspace unavailable.</div>';
  }
}

async function _dashTasks(pane, agent) {
  // Reuse the EXACT task cards from the main Tasks tab (tasksModule.renderTaskList).
  pane.innerHTML = '<button class="agent-act primary" id="dash-newtask" style="margin:4px 0 12px;">+ Assign task</button>'
    + '<div id="dash-task-list"></div>';
  pane.querySelector('#dash-newtask').addEventListener('click', () => _assignTask(agent));
  const listEl = pane.querySelector('#dash-task-list');
  listEl.innerHTML = '<div class="agents-empty">Loading…</div>';
  try {
    const d = await (await fetch(`${API}/api/tasks?crew_member_id=${encodeURIComponent(agent.id)}`, { credentials: 'same-origin' })).json();
    if (window.tasksModule?.renderTaskList) window.tasksModule.renderTaskList(listEl, d.tasks || []);
    else listEl.innerHTML = '<div class="agents-empty">Tasks unavailable.</div>';
  } catch { listEl.innerHTML = '<div class="agents-empty">Couldn\'t load tasks.</div>'; }
}

async function _dashActivity(pane, agent) {
  // Reuse the EXACT activity entries from the main Activity tab.
  pane.innerHTML = '<div id="dash-act-list" class="memory-list"></div>';
  const listEl = pane.querySelector('#dash-act-list');
  listEl.innerHTML = '<div class="agents-empty">Loading…</div>';
  try {
    const d = await (await fetch(`${API}/api/tasks/runs/recent?crew_member_id=${encodeURIComponent(agent.id)}&limit=100`, { credentials: 'same-origin' })).json();
    if (window.tasksModule?.renderActivityRunsInto) window.tasksModule.renderActivityRunsInto(listEl, d.runs || []);
    else listEl.innerHTML = '<div class="agents-empty">Activity unavailable.</div>';
  } catch { listEl.innerHTML = '<div class="agents-empty">Couldn\'t load activity.</div>'; }
}

async function _dashChats(pane, agent) {
  pane.innerHTML = '<div class="agents-empty">Loading…</div>';
  try {
    const r = await (await fetch(`${API}/api/sessions?crew_member_id=${encodeURIComponent(agent.id)}`, { credentials: 'same-origin' })).json();
    const arr = Array.isArray(r) ? r : (r.sessions || []);
    pane.innerHTML = arr.length ? arr.map(s => {
      // Each chat owns its own claude session — show the exact resume command for
      // THIS chat (the id always matches this chat's transcript now).
      const cmd = s.claude_session_id ? `cd data/agents/${agent.id} && claude --resume ${s.claude_session_id}` : '';
      return `
      <div class="dash-row dash-click" data-sid="${esc(s.id)}">
        <div style="flex:1;min-width:0;">
          <div class="dash-row-title">${esc(s.name || 'Chat')}</div>
          <div class="dash-row-meta">${esc(_reltime(s.last_message_at))}${s.message_count ? ` · ${s.message_count} msgs` : ''}</div>
          ${cmd ? `<div class="dash-term"><code class="dash-term-cmd" style="font-size:11px;">${esc(cmd)}</code><button class="agent-act dash-chat-copy" data-cmd="${esc(cmd)}" title="Copy resume command">Copy</button></div>` : ''}
        </div>
      </div>`;
    }).join('') : '<div class="agents-empty">No chats with this agent yet.</div>';
    pane.querySelectorAll('.dash-chat-copy').forEach(btn => btn.addEventListener('click', (e) => {
      e.stopPropagation();
      try { uiModule.copyToClipboard(btn.dataset.cmd); uiModule.showToast('Resume command copied'); } catch (_) {}
    }));
    pane.querySelectorAll('.dash-click').forEach(row => row.addEventListener('click', () => {
      closeManager();
      if (window.sessionModule?.selectSession) window.sessionModule.selectSession(row.dataset.sid);
    }));
  } catch { pane.innerHTML = '<div class="agents-empty">Couldn\'t load chats.</div>'; }
}

// Start a chat that runs AS this agent (backend binds the new session to it).
export async function chatWithAgent(agent) {
  try {
    const fd = new FormData();
    fd.append('name', `${agent.name}`);
    fd.append('crew_member_id', agent.id);
    const res = await fetch(`${API}/api/session`, { method: 'POST', body: fd });
    const p = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(p.detail || `HTTP ${res.status}`);
    closeManager();
    if (window.sessionModule?.selectSession && p.id) {
      await window.sessionModule.selectSession(p.id);
    } else if (p.id) {
      location.reload();
    }
  } catch (e) { uiModule.showError('Could not start chat: ' + e.message); }
}

// ---- Chat header: active-agent chip + picker ----
let _agentCache = null, _agentCacheAt = 0;
async function _agentList(force) {
  if (!force && _agentCache && (Date.now() - _agentCacheAt) < 15000) return _agentCache;
  try { _agentCache = (await _api('', {})).agents || []; _agentCacheAt = Date.now(); } catch { _agentCache = _agentCache || []; }
  return _agentCache;
}

function _sessionCrewId(sessionId) {
  try {
    const ss = window.sessionModule?.getSessions?.() || [];
    const s = ss.find(x => x.id === sessionId);
    return s ? (s.crew_member_id || null) : undefined;  // undefined = not in the loaded list
  } catch { return undefined; }
}

function _hideAgentChip() {
  const btn = document.getElementById('agent-indicator-btn');
  if (btn) { btn.style.display = 'none'; btn.onclick = null; }
}

// Called on every session switch (from sessions.js). Legacy persistent-character
// chats keep the old preset behavior; everything else uses agent binding.
export async function onSessionSwitch(sessionId) {
  _ensureStyles();
  if (!sessionId) { _syncAgentChipForNew(); return; }
  try {
    const map = JSON.parse(localStorage.getItem('odysseus-char-sessions') || '{}');
    if (map && map[sessionId]) {
      const pm = window.presetsModule || (await import('./presets.js')).default;
      if (pm?.onSessionSwitch) pm.onSessionSwitch(sessionId);
      _hideAgentChip();
      return;
    }
  } catch {}
  _syncAgentChip(sessionId);
}

// Is the composer in Agent mode? The default-assistant chip only shows there —
// in plain Chat mode the agent concept is hidden.
function _isAgentMode() {
  try { return (JSON.parse(localStorage.getItem('odysseus-toggles') || '{}').mode || 'chat') === 'agent'; }
  catch { return false; }
}

// Render the chip as a specific bound agent. pickerSessionId is what the chip's
// click hands to the picker (null for a new/pending chat — bind via pending).
function _renderAgentChip(agent, pickerSessionId) {
  const btn = document.getElementById('agent-indicator-btn');
  if (!btn) return;
  const av = document.getElementById('agent-indicator-avatar');
  const nm = document.getElementById('agent-indicator-name');
  if (av) { av.textContent = _initial(agent); av.style.background = _colorFor(agent); }
  if (nm) { nm.textContent = agent.name; nm.style.maxWidth = '90px'; }
  btn.style.display = '';
  btn.title = `Agent: ${agent.name} — click to switch`;
  btn.onclick = () => openAgentPicker(pickerSessionId || null);
}

// Render the chip as the (unbound) default assistant — still clickable to pick.
function _renderDefaultAssistantChip(pickerSessionId) {
  const btn = document.getElementById('agent-indicator-btn');
  if (!btn) return;
  const av = document.getElementById('agent-indicator-avatar');
  const nm = document.getElementById('agent-indicator-name');
  if (av) { av.textContent = '★'; av.style.background = '#5b5b58'; }
  if (nm) { nm.textContent = 'Default assistant'; nm.style.maxWidth = '130px'; }
  btn.style.display = '';
  btn.title = 'Default assistant — click to choose an agent';
  btn.onclick = () => openAgentPicker(pickerSessionId || null);
}

// Single source of truth for the chip: a bound agent shows that agent; unbound
// shows the default assistant in agent mode, and hides in chat mode.
async function _renderChip(crewId, pickerSessionId) {
  const btn = document.getElementById('agent-indicator-btn');
  if (!btn) return;
  if (crewId) {
    const agent = (await _agentList()).find(a => a.id === crewId);
    if (agent) { _renderAgentChip(agent, pickerSessionId); return; }
  }
  if (_isAgentMode()) _renderDefaultAssistantChip(pickerSessionId);
  else _hideAgentChip();
}

async function _syncAgentChip(sessionId) {
  let crewId = _sessionCrewId(sessionId);
  if (crewId === undefined) {
    // Not in the loaded session list yet (e.g. just created) — ask the backend.
    try {
      const r = await fetch(`${API}/api/history/${sessionId}`, { credentials: 'same-origin' });
      crewId = (await r.json()).crew_member_id || null;
    } catch { crewId = null; }
  }
  _renderChip(crewId || null, sessionId);
}

// New/pending chat (no DB session yet): reflect the pending agent pick, or the
// default assistant. Click binds via the pending mechanism in sessions.js.
function _syncAgentChipForNew() {
  const pendingId = window.sessionModule?.getPendingCrewId?.() || null;
  _renderChip(pendingId, null);
}

function _positionPop(pop, anchor, below) {
  if (!anchor) { pop.style.left = '50%'; pop.style.bottom = '92px'; return; }
  const r = anchor.getBoundingClientRect();
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 230)) + 'px';
  if (below) pop.style.top = (r.bottom + 6) + 'px';
  else pop.style.bottom = (window.innerHeight - r.top + 8) + 'px';
}

// Overflow menu for an agent card (Edit / Duplicate / Delete).
function _cardMenu(anchor, agent) {
  document.querySelectorAll('.agent-picker-pop').forEach(p => p.remove());
  const rows = [{ a: 'edit', t: 'Edit with AI' }, { a: 'dup', t: 'Duplicate' }];
  if (!agent.is_default_assistant) rows.push({ a: 'del', t: 'Delete', danger: true });
  const pop = document.createElement('div');
  pop.className = 'agent-picker-pop';
  pop.innerHTML = rows.map(o => `<div class="agent-picker-row${o.danger ? ' danger' : ''}" data-a="${o.a}">${o.t}</div>`).join('');
  document.body.appendChild(pop);
  _positionPop(pop, anchor, true);
  const close = () => { pop.remove(); document.removeEventListener('click', onDoc, true); };
  const onDoc = (e) => { if (!pop.contains(e.target) && e.target !== anchor) close(); };
  setTimeout(() => document.addEventListener('click', onDoc, true), 0);
  pop.querySelectorAll('.agent-picker-row').forEach(row => row.addEventListener('click', () => {
    close();
    const a = row.dataset.a;
    if (a === 'edit') openBuilder({ mode: 'edit', agent });
    else if (a === 'dup') _duplicate(agent);
    else if (a === 'del') _delete(agent);
  }));
}

// "Start from a character" — seed the builder from a built-in persona template.
function _openTemplateMenu(anchor) {
  document.querySelectorAll('.agent-picker-pop').forEach(p => p.remove());
  const chars = (PROMPT_TEMPLATES || []).filter(t => t.isCharacter);
  const pop = document.createElement('div');
  pop.className = 'agent-picker-pop';
  pop.innerHTML = `<div class="agent-picker-title">Start from a character</div>`
    + chars.map(t => `<div class="agent-picker-row" data-id="${esc(t.id)}">
        <span class="agent-picker-av" style="background:${_colorFor({ name: t.name })};">${esc((t.name || '?').charAt(0))}</span><span>${esc(t.name)}</span></div>`).join('');
  document.body.appendChild(pop);
  _positionPop(pop, anchor, true);
  const close = () => { pop.remove(); document.removeEventListener('click', onDoc, true); };
  const onDoc = (e) => { if (!pop.contains(e.target) && e.target !== anchor) close(); };
  setTimeout(() => document.addEventListener('click', onDoc, true), 0);
  pop.querySelectorAll('.agent-picker-row').forEach(row => row.addEventListener('click', () => {
    close();
    const t = chars.find(x => x.id === row.dataset.id);
    if (t) openBuilder({ mode: 'create', seedTemplate: { name: t.name, personality: t.prompt } });
  }));
}

export async function openAgentPicker(sessionId) {
  _ensureStyles();
  sessionId = sessionId || window.sessionModule?.getCurrentSessionId?.();
  // No DB session yet (a brand-new chat) — bind through the pending mechanism so
  // the session is born already assigned. No more "Open a chat first".
  const isNew = !sessionId;
  const agents = await _agentList(true);
  const curId = isNew
    ? (window.sessionModule?.getPendingCrewId?.() || null)
    : (_sessionCrewId(sessionId) || null);
  document.querySelectorAll('.agent-picker-pop').forEach(p => p.remove());
  const pop = document.createElement('div');
  pop.className = 'agent-picker-pop';
  pop.innerHTML = `
    <div class="agent-picker-title">Run this chat as…</div>
    <div class="agent-picker-row${!curId ? ' on' : ''}" data-id="">
      <span class="agent-picker-av" style="background:#5b5b58;">★</span><span>Default assistant</span></div>
    ${agents.filter(a => !a.is_default_assistant).map(a => `
      <div class="agent-picker-row${a.id === curId ? ' on' : ''}" data-id="${esc(a.id)}">
        <span class="agent-picker-av" style="background:${_colorFor(a)};">${esc(_initial(a))}</span><span>${esc(a.name)}</span></div>`).join('')}
    <div class="agent-picker-new" data-act="new">+ New agent</div>`;
  document.body.appendChild(pop);
  const chip = document.getElementById('agent-indicator-btn');
  const anchor = (chip && chip.style.display !== 'none') ? chip
    : (document.getElementById('overflow-plus-btn') || document.getElementById('message'));
  _positionPop(pop, anchor);
  const close = () => { pop.remove(); document.removeEventListener('click', onDoc, true); };
  const onDoc = (e) => { if (!pop.contains(e.target)) close(); };
  setTimeout(() => document.addEventListener('click', onDoc, true), 0);
  pop.querySelectorAll('.agent-picker-row').forEach(row => {
    row.addEventListener('click', async () => {
      close();
      const id = row.dataset.id; // "" = default assistant
      try {
        if (isNew) {
          // A claude_code agent has ONE ongoing chat — open it directly (with its
          // history) instead of starting an empty pending chat that would hide the
          // existing conversation until reload.
          const picked = id ? agents.find(a => a.id === id) : null;
          if (picked && (picked.engine || 'claude_code') !== 'legacy') {
            await chatWithAgent(picked);
            return;
          }
          // No session yet — record the pick; it's applied when the first
          // message materializes the session.
          await window.sessionModule?.bindPendingAgent?.(id || null);
          _syncAgentChipForNew();
          uiModule.showToast(id ? 'Agent set for this chat' : 'Using default assistant');
          return;
        }
        const fd = new FormData();
        // Default assistant row has data-id="" — send an explicit sentinel so it
        // reaches the server as a value (an empty form field arrives as None and
        // the unbind is silently skipped).
        fd.append('crew_member_id', id || '__default__');
        const res = await fetch(`${API}/api/session/${sessionId}`, { method: 'PATCH', body: fd });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (window.sessionModule?.loadSessions) await window.sessionModule.loadSessions();
        _syncAgentChip(sessionId);
        uiModule.showToast(id ? 'Switched agent' : 'Using default assistant');
      } catch (e) { uiModule.showError('Could not switch: ' + e.message); }
    });
  });
  pop.querySelector('[data-act="new"]')?.addEventListener('click', () => { close(); openBuilder({ mode: 'create' }); });
}

const agentsModule = { openManager, closeManager, chatWithAgent, openBuilder, openAgentPicker, onSessionSwitch };
export default agentsModule;
