MISSION: Install, configure, and fully verify Odysseus on this Mac mini (https://github.com/anthonyfegh/odysseusxclaude.git), then iterate until every HTTP endpoint of the app works as intended. The repo is at ~/odysseus (clone it there first if missing: <YOUR-REPO-URL>). You operate autonomously: fix what you can, document everything, never wait for me.

FIRST ACTION: create AUDIT/ inside the repo and save this entire prompt verbatim to AUDIT/MISSION.md — later iterations re-read it from there.

GROUND RULES
- This machine is dedicated to this job. You may install dependencies (Homebrew packages, pip) and modify the working tree. Put any code fixes on a git branch `audit/endpoint-fixes`, one commit per fix with a clear message. Never push.
- Everything stays on 127.0.0.1. Never bind 0.0.0.0, never expose ports.
- The `claude` CLI on this machine is signed in to my subscription (verify: `claude -p "say ok"`). Extra Usage is OFF, so exhausting the allowance pauses things instead of billing. Keep every LLM test prompt tiny ("hi", one-line asks). If you hit "subscription allowance reached", log the timestamp, switch to non-LLM endpoints, and come back later.

REPORTING (create these before anything else, update continuously)
- AUDIT/REPORT.md — running narrative. Every problem gets an entry: symptom (exact error text), root cause, fix or workaround, time lost, and a verdict: ODYSSEUS BUG (upstream-worthy) vs ENVIRONMENT/SETUP vs EXPECTED BEHAVIOR. This report is the product as much as the working app.
- AUDIT/ENDPOINTS.md — master checklist table: method · path · purpose (one line, inferred from code) · class · status · notes.
- AUDIT/STATE.json — loop state: current phase, counts (untested/pass/fail/blocked/deferred), next actions, admin credentials reference, anything a fresh session needs to resume cold.

PHASE 1 — INSTALL & LAUNCH
1. Pre-seed deterministic admin credentials so login is scriptable: export ODYSSEUS_ADMIN_PASSWORD before first setup (check setup.py honors it; if not, capture the temporary password printed on first run). Record the username + password location in STATE.json.
2. Run ./start-macos.sh in the background, logging to AUDIT/logs/app.log. Success looks like the "✓ Odysseus is ready" banner and the app answering on http://127.0.0.1:7860. Every step of the script is idempotent — on failure, read the log, fix, re-run.
3. Sidecar: `./venv/bin/python claude_sidecar/register_endpoint.py` once, then `./claude_sidecar/run.sh` in the background logging to AUDIT/logs/sidecar.log. Success: "▶ Claude sidecar on http://127.0.0.1:8750/v1".
4. Log in over HTTP and store the session cookie for all subsequent tests. Careful: the login rate limiter allows ~15 attempts/min per IP — never brute-loop login.
5. Set the default chat model to a "Claude CLI (subscription)" model — claude-sonnet-4-6 — via the settings API (or UI: Settings → AI Defaults). Never use Haiku for anything agent/tool-related; it fails tool calls by design.

PHASE 2 — ENDPOINT INVENTORY (from code, not guesswork)
Write a small script run inside the venv that imports the FastAPI `app` and dumps every registered route (path, methods, name). Cross-reference routes/*.py for purpose and auth requirements. Fill AUDIT/ENDPOINTS.md completely before testing. Classify every endpoint:
- NORMAL · ADMIN (needs admin session) · LLM (consumes allowance) · LONG-RUNNING (research, task runs — test with minimal configs: 1 round, 60s caps, Run-now) · EXTERNAL-CREDS (email IMAP/SMTP, CalDAV, HF token, paid APIs — without credentials, verify it fails GRACEFULLY with a clear message; that's BLOCKED-OK, not FAIL) · DESTRUCTIVE (wipe/delete-all/danger-zone — defer to the very end, run against expendable data only, and never delete data/auth.json while the loop depends on logging in) · INTERNAL (service-to-service).

PHASE 3 — TEST LOOP
Work through ENDPOINTS.md in batches. For each endpoint: craft a realistic happy-path request with the authenticated session; where cheap, also one bad-input request to confirm error handling. "Works as intended" means behavior matches what the route's code intends — not merely "didn't 500". Create fixtures through the API itself (sessions, notes, documents, agents, tasks, memories) and clean them up after. Statuses: PASS / FAIL / BLOCKED(reason) / DEFERRED-DESTRUCTIVE.
For every FAIL: read the code and logs, diagnose root cause. Environment/config problem → fix it, retest, log it. Genuine code bug → minimal fix on the audit branch, commit, retest, log under "Upstream bugs" in REPORT.md.
KNOWN QUIRKS of this build — verify graceful behavior, do not burn hours "fixing" design decisions: (a) POST /api/tasks/{id}/webhook/{token} is intercepted by auth middleware for external callers; test from localhost/logged-in context and document the limitation. (b) Several admin features are API-only with no wired UI: API tokens, outgoing webhooks, feature toggles, RAG upload — test the API surface and note "no UI in this build". (c) MCP one-click presets are dead code; the generic add form is the live path. (d) The sidecar has no vision — image input degrades to a text description via the vision-model path or "[image omitted]".

PHASE 4 — CONVERGENCE
Done means: every endpoint is PASS or justified BLOCKED/known-quirk, AND two consecutive full passes produced zero new failures. Then finalize AUDIT/REPORT.md with: executive summary, setup timeline (every problem in order), the endpoint scoreboard, the upstream bug list with commit hashes, and recommendations for making Odysseus installs smoother. Create the file AUDIT/DONE and print exactly: AUDIT COMPLETE.

/loop  until youre done

---

ADDENDUM TO MISSION — agent-mode (claude_code) is a separate test surface; append this to AUDIT/MISSION.md and treat it as required for convergence.

Your /api/chat and /api/chat_stream tests so far only exercised the sidecar path (session created with explicit endpoint_url=http://127.0.0.1:8750/..., no crew_member_id) — that routes around the agent machinery entirely. The whole point of agent mode in this build is that chats run on the claude_code engine (Claude Code CLI as a real agent: persistent session via resume, Claude Code executes its own tools in the agent workspace), NOT the stateless claude -p reasoning shim. Evidence: commits d59ad80 (no-agent chats default to claude_code), 2e0d17d (claude session bound to the chat, resume-id fix), 1b753f5 (claude_code agent awareness prompt), agent_uses_claude_code() in session_routes.py, claude_session_id on session rows, _agents_defaulted_to_claude_code: true in settings.

Add these tests (read src/crew_service.py and the claude_code agent service code first to confirm exact mechanics):

Agent-bound chat turn: create/open a session bound to a claude_code agent — the seeded default assistant crew (id in startup log: 68dd96fd-...), via POST /api/session -F crew_member_id=<id> — then run one tiny chat_stream turn ("say ok"). Verify the turn runs through the claude_code path (check which process spawns / logs), not the sidecar.
Session binding/reuse: confirm claude_session_id gets set on the chat after the first turn, a second tiny turn resumes the SAME claude session (regression for 2e0d17d), and re-opening the agent's chat reuses the one bound session instead of creating a new one.
Agent tool use: one minimal turn that forces a tool ("list the files in your workspace") and verify Claude Code executed its own tool (workspace evidence / tool events in the stream), as opposed to Odysseus sentinel dispatch.
Reclassify/annotate in ENDPOINTS.md: which chat/agent endpoints have BOTH paths, and record that the sidecar tests alone don't cover them. Both paths must PASS for convergence.
Keep prompts tiny (allowance rules unchanged). Log findings in REPORT.md under a new "Agent-mode (claude_code) path" section.
