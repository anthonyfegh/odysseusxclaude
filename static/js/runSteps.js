/**
 * runSteps.js — read-only renderer for a task run's recorded step transcript.
 *
 * Maps the persisted `{"k":...}` step list (same schema the agent loop produces,
 * see task_scheduler.py) onto the SAME `.agent-thread-*` / `.thinking-section`
 * DOM the live chat uses, so Activity can replay an agent's full work with the
 * familiar visuals. Pure string builder — no streaming, tickers, or side effects.
 * Tool-node fold/expand is handled by the global delegated header click handler
 * in chat.js, so injected nodes are interactive for free.
 */

import markdownModule from './markdown.js';

const API_BASE = window.location.origin;

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Friendly verbs for common tools (mirrors chat.js _toolLabels, kept local so
// this module stands alone). Falls back to the raw tool name.
const TOOL_LABELS = {
  web_search: 'Searching', web_fetch: 'Fetching', bash: 'Running', python: 'Running',
  create_document: 'Writing', update_document: 'Writing', read_document: 'Reading',
  edit_file: 'Editing', read_file: 'Reading', write_file: 'Writing', list_files: 'Browsing',
  image_gen: 'Generating', generate_image: 'Generating',
  manage_memory: 'Remembering', search_memory: 'Recalling',
  manage_session: 'Organizing', deep_research: 'Researching', list_models: 'Browsing',
  ui_control: 'Adjusting', classify_llm: 'Classifying',
};
function toolLabel(tool) {
  const l = (tool || '').toLowerCase();
  return TOOL_LABELS[l] || tool || 'tool';
}

function mdProse(text) {
  try {
    return markdownModule.processWithThinking(markdownModule.squashOutsideCode(text || ''));
  } catch {
    return `<pre style="white-space:pre-wrap;word-break:break-word;">${esc(text || '')}</pre>`;
  }
}

// Build one completed tool-thread node (mirrors chat.js:2020, static).
function toolNode({ tool, command, output, exit_code, running }) {
  const ok = (exit_code === 0 || exit_code == null);
  const icon = running ? '▶' : (ok ? '✓' : '✗');
  const status = running ? '' : `<span class="agent-thread-status">${ok ? 'done' : 'failed'}</span>`;
  const cmdHtml = command ? `<pre class="agent-thread-cmd">${esc(command)}</pre>` : '';
  const outHtml = (output && String(output).trim())
    ? `<details class="agent-tool-output"><summary>Output</summary><pre>${esc(output)}</pre></details>`
    : '';
  return (
    `<div class="agent-thread-node${ok || running ? '' : ' error'}">` +
      `<div class="agent-thread-dot"></div>` +
      `<div class="agent-thread-header">` +
        `<span class="agent-thread-icon">${icon}</span>` +
        `<span class="agent-thread-tool">${esc(toolLabel(tool))}</span>` +
        status +
        `<span class="agent-thread-chevron">▶</span>` +
      `</div>` +
      `<div class="agent-thread-content">${cmdHtml}${outHtml}</div>` +
    `</div>`
  );
}

/**
 * Render a recorded step list → HTML string. Returns '' for an empty transcript.
 */
export function renderRunSteps(steps) {
  if (!Array.isArray(steps) || !steps.length) return '';
  const out = [];
  let threadOpen = false;
  let pendingStart = null; // {tool, command} awaiting its tool_output

  const openThread = () => { if (!threadOpen) { out.push('<div class="agent-thread">'); threadOpen = true; } };
  const flushPending = () => {
    if (pendingStart) { openThread(); out.push(toolNode({ ...pendingStart, running: true })); pendingStart = null; }
  };
  const closeThread = () => {
    flushPending();
    if (threadOpen) { out.push('</div>'); threadOpen = false; }
  };

  for (const s of steps) {
    const k = s && s.k;
    if (k === 'tool_start') {
      flushPending();                       // a start with no output → flush prior
      pendingStart = { tool: s.tool, command: s.command || '' };
    } else if (k === 'tool_output') {
      openThread();
      const cmd = (pendingStart && pendingStart.tool === s.tool) ? pendingStart.command : (s.command || '');
      pendingStart = null;
      out.push(toolNode({ tool: s.tool, command: cmd, output: s.output, exit_code: s.exit_code }));
    } else if (k === 'text') {
      closeThread();
      if ((s.text || '').trim()) out.push(`<div class="msg task-step-text">${mdProse(s.text)}</div>`);
    } else if (k === 'thinking') {
      closeThread();
      if ((s.text || '').trim()) {
        out.push(`<details class="thinking-section task-step-thinking"><summary>Thinking</summary>` +
                 `<div class="thinking-content-static">${mdProse(s.text)}</div></details>`);
      }
    } else if (k === 'web_sources' && (s.count || (s.sources && s.sources.length))) {
      closeThread();
      out.push(`<div class="task-step-note">🔎 ${esc(s.count || (s.sources || []).length)} source(s)</div>`);
    } else if (k === 'document' && s.title) {
      closeThread();
      out.push(`<div class="task-step-note">📄 ${esc(s.title)}</div>`);
    }
    // agent_step / metrics → skipped
  }
  closeThread();
  return `<div class="task-run-steps">${out.join('')}</div>`;
}

/**
 * Fetch a run's persisted steps and render them into mountEl.
 */
export async function fetchAndRenderRunSteps(runId, mountEl) {
  if (!runId || !mountEl) return;
  mountEl.innerHTML = '<div class="task-step-note" style="opacity:.6;">Loading…</div>';
  try {
    const res = await fetch(`${API_BASE}/api/tasks/runs/${encodeURIComponent(runId)}/steps`, { credentials: 'same-origin' });
    if (!res.ok) {
      mountEl.innerHTML = `<div class="task-step-note">Couldn't load details (HTTP ${res.status})</div>`;
      return;
    }
    const data = await res.json();
    const html = renderRunSteps(data.steps);
    mountEl.innerHTML = html || '<div class="task-step-note" style="opacity:.6;">No detailed steps recorded for this run.</div>';
  } catch (e) {
    mountEl.innerHTML = `<div class="task-step-note">Couldn't load details: ${esc(e && e.message || e)}</div>`;
  }
}

export default { renderRunSteps, fetchAndRenderRunSteps };
