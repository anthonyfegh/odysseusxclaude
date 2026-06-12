# Odysseus: Fixes and Issues for Tony

Everything we hit while building the course on Kate's machine (branch: main). Items marked **FIXED LOCALLY** are live on this machine only and need upstreaming. Items marked **OPEN** are not fixed. Listed roughly by impact. File and line references included where known.

---

## 1. Google Workspace email needs OAuth — OPEN

**What we hit.** A normal @gmail.com connected fine with an App Password. But `contact@oliviolabs.com` (Google Workspace) would not show an App Password at all ("the setting you are looking for is not available"), even with 2-Step Verification on. It only worked after enabling 2-Step Verification on the user *and* adjusting Workspace admin settings — and Google is actively deprecating app passwords in favor of OAuth.

**Why it matters.** All the students use Google Workspace. Odysseus only connects email by password (IMAP App Password). If a student's domain has app passwords disabled, the account cannot be connected at all.

**Suggested fix.** Add Google OAuth as a connection method for Gmail/Workspace. Until then, document the Workspace admin steps (see the Workspace addendum).

---

## 2. Per-agent tool toggles do not control Claude Code's native tools — PARTIALLY ADDRESSED, STILL BROKEN

**What we hit.** The Morning Assistant (Scout) has web search toggled OFF, but it still researches the web. The per-agent Tools checkboxes only gate Odysseus's own `mcp__odysseus__*` tools; the agent still has Claude's native WebSearch, WebFetch, Bash, Read, Write, Edit. So "web search off" is not enforced.

**What we tried (helped but did not fully fix it).**

- `src/claude_code_engine.py`: `--disallowedTools` is now derived from the agent's `enabled_tools`; if `web_search` is off, native WebSearch/WebFetch are also disallowed. (Confirmed at the CLI: `--disallowedTools "WebSearch WebFetch"` does block native web, even on `--resume`.)
- `claude_sidecar/run.sh`: `CLAUDE_SIDECAR_NATIVE_TOOLS=Read,Glob,Grep`, dropping web tools so plain/unbound chats on the sidecar cannot browse. (Confirmed: a sidecar chat now replies NO_WEB_TOOL.)

**Current status: STILL BROKEN.** Despite both changes, Scout still web-searches in the app. The sidecar is confirmed web-free, so Scout's chat is reaching web by another route. Most likely cause to investigate: an agent-mode chat that is not bound to a specific agent falls back to the DEFAULT assistant crew (which has `web_search` enabled), so it runs on the agent engine with web allowed; or the per-agent disallow is not being applied to that chat's process.

**Suggested fix for Tony.**
- Make sure a chat that is supposed to run as a specific agent actually binds to that agent (not the default assistant), and that the engine applies that agent's `--disallowedTools` every turn.
- Extend the gating beyond web search: native Bash, Read, Write, Edit are still available to every agent regardless of toggles.
- Consider routing every agent-bound chat through the agent engine so per-agent tools are always authoritative, rather than the sidecar.

---

## 3. Agent builder returns a raw 500 when no Default Chat Model is set — OPEN

**What we hit.** A fresh install registers the sidecar endpoint but does not set it as the Default Chat Model. The agent builder then fails with HTTP 500 and "No model endpoint configured."

**Where.** `src/agent_builder.py:193`

**Suggested fix.** On setup, auto-select the only enabled endpoint as the Default Chat Model. Have the builder return a friendly message instead of a 500.

---

## 4. Email tools could not read Sent, Drafts, or Trash on Gmail — FIXED LOCALLY, please upstream

**What we hit.** Asking an agent about sent mail returned "I can't access the Sent folder." Gmail's sent folder is `[Gmail]/Sent Mail`, not `Sent`; the tool used the literal name and failed.

**Fix applied.** Added sent/drafts to the folder resolver (role flags and candidate names), made the list path resolve the folder, and quoted folder names with spaces. In `mcp_servers/email_server.py` (agent path) and `routes/email_routes.py` (web UI path). Verified working.

**Note.** Other `conn.select(folder)` calls in `mcp_servers/email_server.py` (lines ~542, 653, 856, 898, 920, 978, 990, 1034) also do not quote and would fail on folder names with spaces.

---

## 5. Scheduled task captured narration instead of the final answer — OPEN

**What we hit.** A Morning Brief run emailed only the agent's narration ("Pulling email and calendar now. Let me read the most important emails for") with no actual brief. The saved result was just those interim text lines.

**Suggested fix.** Capture the final assistant message as the task result, not interim "thinking out loud" text that precedes tool calls.

---

## 6. A hung run was marked "success" with a partial result — OPEN

**What we hit.** A task run sat from 07:52 to 08:38 (~46 minutes) and was then marked status "success" with a 77-character partial result, which got emailed.

**Suggested fix.** Tighter timeout for scheduled runs, and mark empty or clearly-partial output as failed, not success.

---

## 7. Task email delivery is plain text only — OPEN

**What we hit.** Emailed briefs showed raw Markdown (literal `#`, `**`, and table pipes) because delivery sends `text/plain` via `set_content` with no Markdown-to-HTML conversion.

**Where.** `_deliver_via_email` in `src/task_scheduler.py`

**Suggested fix.** Render the result Markdown to HTML and send multipart (plain text + HTML). Also consider a cleaner Subject than "[Task] ".

---

## 8. Scheduled tasks drift by an hour across daylight saving — OPEN

**What we hit.** Task times are stored as a fixed UTC offset. The code supports an IANA timezone but passes `None`.

**Where.** `src/task_scheduler.py:2624` (`timezone=None`)

**Suggested fix.** Add a per-user or app timezone setting and pass it into `compute_next_run`.

---

## 9. Web search has no backend on the native macOS install — NOTE

**What we hit.** SearXNG (default search backend at `localhost:8080`) only runs in the Docker setup, not the native `start-macos.sh` install. Web search still works via a DuckDuckGo HTML fallback, but it is less robust (some sites return 401, no PDF extraction).

**Suggested fix (optional).** Bundle or auto-start a search backend for the native install, or document setting a SerpAPI / Google Custom Search key.

---

## Already working as intended (no action needed)

- **Deep research fan-out is blocked.** The engine disallows Workflow, Task, Agent, and Skill, and `trigger_research` is gated (returns 403). Desired behavior after an earlier cost blowup.
- **Calendar connects via Settings > Calendar** using a CalDAV account or an `.ics` subscription (Google secret iCal address). The `.ics` path is verified working.

---

## Cost reminder (operational, not a bug)

A chat had quietly switched to Opus (~5× the cost of Sonnet). Worth a default-to-Sonnet nudge or a visible warning when a session is on Opus.
