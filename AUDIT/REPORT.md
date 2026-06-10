# Odysseus Endpoint Audit — Running Report

**Machine:** Mac mini, Darwin 24.3.0 · **Repo:** ~/odysseus (clone of https://github.com/anthonyfegh/odysseusxclaude.git)
**Audit started:** 2026-06-10
**Mission:** see AUDIT/MISSION.md

## Executive summary

Odysseus installed and launched cleanly on this Apple-Silicon Mac mini on the first run of `./start-macos.sh` (Homebrew python3.12 arm64, all system deps present). The app, the Claude subscription sidecar, ChromaDB, and the built-in MCP servers all came up; admin login, the default-model wiring, and end-to-end chat (both the stateless `claude -p` sidecar path and the persistent `claude_code` agent engine) all work.

**436 HTTP endpoints** were inventoried directly from the live FastAPI route table and classified. After testing: **393 PASS, 43 BLOCKED (all justified — graceful degradation without external credentials or optional deps), 0 FAIL.** Every endpoint either works as its code intends or fails gracefully with a clear message.

The audit found and fixed **12 genuine code bugs** (branch `audit/endpoint-fixes`, one commit each, never pushed). Three were severe: the subscription sidecar 500'd on every non-streaming completion against the installed claude CLI (version drift), its own probe UI hid all of its models, and every agent-bound non-streaming `/api/chat` 502'd. Three history endpoints 500'd unconditionally on a wrong column name. The rest were a data-corrupting skill-rename, an auth-middleware error-swallow, a shell-quoting bug, a graceful-degradation inconsistency, and a class of unguarded `int()` parses that 500'd on bad input (found by the convergence pass's bad-input probing).

The single most impactful install friction: **the Claude sidecar — this build's headline feature — was broken out of the box** against the current `claude` CLI. See Recommendations.

## Status — AUDIT COMPLETE (2026-06-10 19:50 CEST)

- **Convergence achieved:** passes 4 and 5 (full 27-batch fleet, 386 endpoints each) returned **zero failures**, after passes 1-3 found 10 endpoint bugs (+2 found manually) that were fixed on the audit branch. Final scoreboard: **393 PASS · 43 justified BLOCKED · 0 FAIL** of 436 endpoints.
- App: RUNNING on http://127.0.0.1:7860 (uvicorn, loopback only) — final LLM spot-check green on both chat paths (sidecar + claude_code agent engine)
- Sidecar: RUNNING on http://127.0.0.1:8750/v1 (claude-sonnet-4-6 / opus-4-8 / haiku-4-5)
- Branch `audit/endpoint-fixes`: 12 commits (list below), never pushed
- All audit fixtures cleaned up (users: admin only; tokens: none; audit-tmp sessions/skills/images/memories: none). One inert 70-byte PNG remains in data/uploads (no delete API exists for uploads — by design).

## Convergence record

| Pass | Scope | Result |
|------|-------|--------|
| 1 | full fleet (27 batches, 387 endpoints) + manual LLM/long-running/destructive rounds | 7 fleet FAILs + 2 manual FAILs -> all fixed |
| 2 | full fleet | 2 new FAILs (bad-input 500s) -> fixed; ~22 spurious BLOCKED from a harness session race, reconfirmed PASS |
| 3 | fleet (24/27; 3 batches died on harness socket errors) | 1 new FAIL (cookbook/state token poisoning) -> fixed |
| 4 (attempt 1) | aborted — subscription session limit (logged below) | n/a |
| 4 | full fleet, lean verify | **0 FAIL** (clean streak 1) |
| 5 | full fleet, lean verify | **0 FAIL** (clean streak 2 -> converged) |

## Setup timeline

| # | When | Event |
|---|------|-------|
| 1 | 2026-06-10 16:05 | Cloned repo to ~/odysseus (main @ 1b753f5). Created AUDIT scaffolding. |
| 2 | 2026-06-10 16:07 | `./start-macos.sh` ran clean on first try (python3.12 arm64, brew deps present). Port 7860 up after ~68s. |
| 3 | 2026-06-10 16:08 | setup.py honored ODYSSEUS_ADMIN_PASSWORD; admin user `admin` created. |
| 4 | 2026-06-10 16:09 | Sidecar registered (`claude-cli-sidecar`) and started on :8750; /v1/models OK. |
| 5 | 2026-06-10 16:10 | Logged in via POST /api/auth/login; cookie saved. Set default/utility model to claude-sonnet-4-6 via POST /api/auth/settings. |
| 6 | 2026-06-10 16:12 | Startup warnings fixed: started ChromaDB docker container on 127.0.0.1:8100 (W1); pre-installed @playwright/mcp via npx (W2, needs app restart to register). |
| 7 | 2026-06-10 16:25–17:10 | Found+fixed sidecar JSON-array 500 (P1), probe hidden-models bug (P2). Inventory workflow: 436 endpoints. Manual LLM round: chat/stream/rewrite/compact/parse/probe etc. all green via sidecar. |
| 8 | 2026-06-10 17:15–17:45 | Agent-mode addendum: claude_code engine verified (process fingerprints, --resume continuity, native tool use). Found+fixed agent-path /api/chat 502 (P3). |
| 9 | 2026-06-10 17:50–18:20 | Round-1 fleet (27 agents): 340/387 PASS, 7 FAIL → all diagnosed+fixed (P4–P9). PyMuPDF installed; app restarted; all retests green. |
| 10 | 2026-06-10 18:20–18:40 | Long-running + destructive rounds: model download/serve, assistant run, wipes, sessions/all — all green; login survives. |
| 11 | 2026-06-10 18:45–19:06 | Convergence passes 2–3: 3 more bugs found+fixed (P10–P12). Pass-4 attempt aborted on subscription session limit (reset 19:00). |
| 12 | 2026-06-10 19:10–19:50 | Passes 4 and 5 (lean verify, full fleet): 0 FAIL each — converged. Final LLM spot-checks green. Fixtures swept. AUDIT/DONE created. |

## Problems encountered

### W1 — ChromaDB not reachable at startup
- **Symptom:** `ToolIndex init failed (will retry in 30.0s): ChromaDB is not reachable at localhost:8100. Start the ChromaDB service (e.g. docker compose up chromadb) or set CHROMADB_HOST / CHROMADB_PORT...`
- **Root cause:** App ships only `chromadb-client` (HTTP client) and expects a standalone Chroma server on :8100; native macOS quick-start doesn't start one.
- **Fix/workaround:** `docker run -d --name odysseus-chroma -p 127.0.0.1:8100:8000 -v ~/odysseus/data/chroma-docker:/chroma/chroma chromadb/chroma`. ToolIndex retries every 30s and picks it up without restart.
- **Time lost:** ~5 min
- **Verdict:** ENVIRONMENT/SETUP — but a smoother-install recommendation: start-macos.sh could detect Docker and offer to start Chroma, or the warning could mention the exact docker run command for the native path.

### W2 — Built-in Browser MCP unavailable (Playwright)
- **Symptom:** `Built-in: Browser is not available. Reason: npm package '@playwright/mcp@latest' is not installed in the npx cache.`
- **Root cause:** First run on a clean machine; npx cache empty. Self-documented fix in the log.
- **Fix/workaround:** `npx -y @playwright/mcp@latest --version` once; app restart scheduled before Phase 3.
- **Time lost:** ~2 min
- **Verdict:** EXPECTED BEHAVIOR (optional dep, graceful degradation, clear message)

Format for entries:
### P<N> — <title>
- **Symptom:** exact error text
- **Root cause:**
- **Fix/workaround:**
- **Time lost:**
- **Verdict:** ODYSSEUS BUG | ENVIRONMENT/SETUP | EXPECTED BEHAVIOR

### P1 — Sidecar 500 on every non-streaming completion
- **Symptom:** `POST /v1/chat/completions` (stream=false) → HTTP 500 "Internal Server Error"; sidecar log: `AttributeError: 'list' object has no attribute 'get'` at claude_sidecar/sidecar.py:552.
- **Root cause:** claude CLI v2.1.x emits a JSON **array** of events (`[system, assistant, rate_limit_event, result]`) for `--output-format json`; the sidecar was written against an older CLI that emitted the bare `result` object (its docstring even documents the old shape, "verified against claude v2.1.161").
- **Fix:** pick the `type=="result"` item when output parses to a list — commit `9b8061c` on audit/endpoint-fixes. Verified: non-streaming, streaming, and tool-sentinel paths all pass.
- **Time lost:** ~20 min
- **Verdict:** ODYSSEUS BUG (CLI version drift; upstream-worthy)

### P2 — Endpoint probe hides every sidecar model (8s hardcoded timeout)
- **Symptom:** `GET /api/model-endpoints/claude-cli-sidecar/probe` → all 3 models `"Timed out (8s)"`, `probe_done ... hidden: 3` — and the route **persisted** `hidden_models=[all three]`, removing the whole endpoint's models from /api/models pickers. `POST /api/probe-selected` passed only by luck at 7962ms.
- **Root cause:** `_probe_single_model` called with hardcoded `timeout=8` at three sites (routes/model_routes.py 787/849/1101 pre-fix); the sidecar spawns a fresh `claude` process per completion with ~8–10s cold start. The per-endpoint probe writes failures to `hidden_models`.
- **Fix:** immediate remediation `PATCH /api/model-endpoints/claude-cli-sidecar/models {"hidden":[]}`; code fix `ODYSSEUS_PROBE_TIMEOUT` env (default 30s) used at all three sites — commit `1d7f660`. Retest scheduled after app restart.
- **Time lost:** ~25 min
- **Verdict:** ODYSSEUS BUG (a first-class feature of this build — the subscription sidecar — is unusable with its own probe UI)

### N1 — Minor notes (not bugs)
- `POST /api/v1/chat` with no session resolves model "auto" to the **first advertised model** of the first enabled endpoint (claude-opus-4-8), not the configured default (sonnet). Code-intended (webhook_routes.py case 3), but a default-model preference would be friendlier. EXPECTED BEHAVIOR + recommendation.
- `POST /api/email/extract-style` with no email account returns `{"success":false,"error":"[Errno 61] Connection refused"}` — graceful (200, no traceback) but the message should say "no email account configured". EXPECTED BEHAVIOR + polish recommendation.
- `POST /api/session` and `/api/gallery/upload` take **form fields** (`-F`), `/api/upload` wants field name `files`, gallery wants `file` — inconsistent but documented here for testers.

## Agent-mode (claude_code) path

Per mission addendum: agent-bound chats run on the **claude_code engine** (real Claude Code CLI agent: persistent `--resume` session, own tools in the agent workspace), not the stateless `claude -p` sidecar shim. Routing rule confirmed in code: `agent_uses_claude_code()` (src/crew_service.py:214) — any crew-bound turn → claude_code unless `engine='legacy'` or the global `claude_code_engine_enabled` kill-switch is off; unbound agent-mode chats borrow the default assistant (chat_routes.py:359, commit d59ad80).

**Test results (all prompts tiny):**

1. **Agent-bound chat turn — PASS.** `POST /api/session -F crew_member_id=68dd96fd-…` returned the agent's pinned chat `a7a3a5df-…` (one-chat-per-agent reuse, not a new session). `chat_stream` "say ok" on it: first SSE event `{"type":"model_info","model":"","engine":"claude_code"}`; mid-turn `ps` showed `claude --print --session-id 0e43dc97-… --input-format stream-json … --permission-mode bypassPermissions --mcp-config <odysseus proxy>`; the sidecar's access log did not move during the turn. Engine path confirmed, sidecar not involved.
2. **Session binding / resume (2e0d17d regression) — PASS.** After turn 1 the chat row has `claude_session_id=0e43dc97-…`. Turn 2 spawned `claude --print --resume 0e43dc97-…` (same uuid) and correctly answered "what word did you just say?" with "ok" — transcript continuity only possible by resuming the same claude session. Re-opening via `POST /api/session -F crew_member_id=…` again returns `a7a3a5df` (reuse verified).
3. **Agent tool use — PASS.** "list the files in your workspace" produced native engine events: `tool_start {tool:"bash", command:"ls /Users/clawdio/odysseus/data/agents/68dd96fd-…", tool_use_id:"toolu_01D8…"}` → `tool_output {exit_code:0}` → `agent_step round 2` → final text. That is Claude Code executing its own Bash tool in the agent workspace (Anthropic-native `toolu_` ids), not Odysseus `__ODY_TOOL__` sentinel dispatch.
4. **Dual-path gap found — non-streaming `/api/chat` (P3 below).** The engine dispatch existed only in `chat_stream`; `/api/chat` on an agent-bound session 502'd. Fixed on the audit branch; retest pending app restart.

**Dual-path endpoints annotated in ENDPOINTS.md:** `/api/chat` (both paths required), `/api/chat_stream` (both PASS), `/api/session` (agent reuse path PASS), `/api/assistant/run/{id}` and `/api/tasks/{id}/run` (engine choice follows the task's crew), `/api/rewrite` + `/api/session/{id}/compact` flagged legacy-only (round-2 check on agent sessions).

Sidecar-path tests alone do NOT cover these endpoints; convergence requires both paths green.

### P3 — Non-streaming /api/chat 502s on agent-bound (claude_code) sessions
- **Symptom:** `POST /api/chat {"message":"say ok","session":"<agent chat>"}` → HTTP 502 `{"detail":"POST  failed after 3 attempts: Request URL is missing an 'http://' or 'https://' protocol."}`; log shows `llm_call_async` retrying against an empty URL.
- **Root cause:** the crew/claude_code dispatch lives only in the `chat_stream` handler (routes/chat_routes.py:729); the non-streaming `chat_endpoint` feeds `sess.endpoint_url` (empty for agent-bound chats — the engine doesn't use endpoints) straight into `llm_call_async`.
- **Fix:** mirror the dispatch in `chat_endpoint`: resolve the session crew, and when `agent_uses_claude_code`, drain `stream_claude_code_session` deltas into a single `{"response": …}` with the same persistence — commit `226b8c6`. Retest after app restart.
- **Time lost:** ~30 min
- **Verdict:** ODYSSEUS BUG (the build's own default — d59ad80 — makes every agent chat claude_code; its non-streaming API endpoint was incompatible with that default)

### N2 — Agent-mode cosmetic note
- `model_info` on the claude_code path streams `"model": ""` when the crew has no explicit model (chat_routes.py:709 uses `sess.model` before the engine resolves its sonnet default; metrics later carry the real model). Cosmetic; recommendation only.

## Round-1 fleet — bugs found & fixed (27-agent parallel pass over 387 endpoints)

Fleet result: **340 PASS, 40 BLOCKED (graceful no-creds / optional-dep), 7 FAIL.** All 7 FAILs diagnosed, fixed on the audit branch, and retested green after restart.

### P4 — Three history endpoints 500 unconditionally (`ChatMessage.created_at`)
- **Symptom:** `POST /api/session/{id}/mark-stopped`, `/update-last-meta`, `/merge-last-assistant` → 500 `type object 'ChatMessage' has no attribute 'created_at'`.
- **Root cause:** the DB model `core.database.ChatMessage` column is `timestamp`, not `created_at`; all three `.order_by(DbChatMessage.created_at)` raised AttributeError (caught by each route's broad except). merge/mark also mutated in-memory history *before* the crash, so the API reported failure on half-applied state.
- **Fix:** `028064a` — `.created_at` → `.timestamp` (3 sites). Retest: all 200.
- **Verdict:** ODYSSEUS BUG.

### P5 — `/api/presets/groups` 500 on malformed JSON
- **Symptom:** non-JSON body → 500 + uncaught `JSONDecodeError` traceback (should be 400).
- **Root cause:** `save_group_presets` did `await request.json()` with no guard (preset_routes.py:119).
- **Fix:** `7789aa1` — wrap + validate object shape → 400. Retest: 400.
- **Verdict:** ODYSSEUS BUG (minor; input validation).

### P6 — `/api/skills/{id}/markdown` silently renames skill on garbage input
- **Symptom:** body without YAML frontmatter → 200 and the target skill is renamed/moved to `"skill"` on disk (documented contract: 400 "Could not parse SKILL.md").
- **Root cause:** `parse_frontmatter()` returns `({}, text)` (never raises) for non-`---` input; `from_markdown` then slugs an empty name to the `"skill"` fallback, and `save_skill_markdown` writes it.
- **Fix:** `8975b00` — validate frontmatter + name presence in the route, 400 if absent. Retest: 400, no rename.
- **Verdict:** ODYSSEUS BUG (data-corrupting — destructive side effect on a "save" path).

### P7 — `GET /backgrounds` 500 + auth middleware swallows downstream errors
- **Symptom:** cookie users → 500 (`FileNotFoundError`); via internal-tool path → misleading 302 /login.
- **Root cause:** (1) `serve_backgrounds` opened a missing `static/backgrounds.html` unconditionally; (2) the internal-tool bypass wrapped `return await call_next(request)` inside `try/except Exception: pass`, so *any* downstream handler error on an internal-tool request was swallowed and fell through to the cookie path → 302.
- **Fix:** `b710221` — 404 when the file is absent; move `call_next` outside the guard so only token validation is caught. Retest: 404 on both paths.
- **Verdict:** ODYSSEUS BUG (the middleware part is the more serious — it masks real 4xx/5xx on the entire internal-tool surface).

### P8 — `/api/cookbook/setup` shell-quote collision + false success
- **Symptom:** any remote host → 200 `{"ok":true,"output":"/bin/sh: -c: line 0: syntax error near unexpected token '('"}` — reports success while nothing ran.
- **Root cause:** the remote `setup_script` (containing its own single-quoted substrings) was wrapped in naive outer single quotes for `ssh host '...'`; the inner quote closed early → local `/bin/sh -c` aborted. And `ok = "OK" in output` matched the echoed-back `print("OK")` literal.
- **Fix:** `1dc3c8b` — `shlex.quote(setup_script)` for both ssh branches; `ok = returncode==0 and "OK" in output`. Retest: `{"ok":false,"output":"Host key verification failed."}` (real ssh error).
- **Verdict:** ODYSSEUS BUG (EXTERNAL-CREDS remote feature, but the quoting + false-positive are real defects).

### P9 — PDF export/render 500 (not graceful 503) when PyMuPDF missing
- **Symptom:** `export-pdf` / `render-pdf` → 500 when optional PyMuPDF absent, while sibling viewer routes (`page/{n}.png`, `render-pages`) return a graceful 503.
- **Root cause:** the fill routes caught `fill_fields()`'s missing-dep `RuntimeError` under a broad `except Exception` → 500.
- **Fix:** `abcc7cd` — branch on the PyMuPDF-missing message → 503 (matching siblings); real failures stay 500. Also installed PyMuPDF in the venv so all PDF happy paths now PASS (200).
- **Verdict:** ODYSSEUS BUG (graceful-degradation inconsistency) + ENVIRONMENT (optional dep).

## Convergence pass 2 — 2 new bad-input bugs found & fixed

A second full 27-agent fleet pass (zero new happy-path failures) surfaced **2 new FAILs**, both the same class as P5 — an unguarded `int()` on request input returning 500 instead of 400:

### P10 — `GET /api/hwfit/models?gpu_count=abc` → 500
- **Root cause:** `n = int(gpu_count)` with no guard (hwfit_routes.py:151); the sibling `gpu_group` parse right above it *was* guarded.
- **Fix:** `58a3e2e` — try/except → 400 "gpu_count must be an integer". Retest: 400; valid params still 200.

### P11 — `PUT /api/email/config` (and account create/update/test) with non-numeric port → 500
- **Root cause:** `val = int(val)` on `*_port` body fields with no guard (email_routes.py:2832, plus 2934/2939/2982/3091/3125).
- **Fix:** `58a3e2e` + `0288f3c` — guard every port parse across config, account create, account update, and test-connection → 400. Retest: 400; valid config still 200.

**Proactive sweep:** grepped all `int()`/`float()` parses of request input across `routes/*.py`; verified the other candidates (gallery rotate/scale, search count, calendar tz-offset) already degrade gracefully (400 / try-except / `or`-default). Pass 2's memory+notes batch spuriously BLOCKED ~22 endpoints after its own agent's admin session got into a bad state mid-batch (a harness race with the concurrent auth-logout agent, not an app fault) — all 22 reconfirmed PASS with the admin cookie immediately after. Kept their round-1 PASS.

### Dead/shadowed route (documented, not fixed)
- `GET /api/history/{session_id}` (history_routes, mounted at app.py:528) is shadowed by `GET /api/history/{sid}` from session_routes (mounted first, app.py:500) — FastAPI first-match wins, so the history_routes handler is unreachable. Behavior-preserving to leave; noted for upstream cleanup. Same family as the documented "MCP one-click presets are dead code" quirk.

## Upstream bugs (ODYSSEUS BUG verdicts, with audit-branch commit hashes)

1. **`9b8061c`** — sidecar: non-streaming path crashes (HTTP 500) on JSON-array output from claude CLI ≥2.1.x (`sidecar.py:552`).
2. **`1d7f660`** — models: hardcoded 8s per-model probe timeout marks all claude-CLI-sidecar models failed; `/api/model-endpoints/{id}/probe` then persists them into `hidden_models`, hiding the endpoint from pickers.
3. **`226b8c6`** — chat: non-streaming `/api/chat` had no claude_code dispatch — every agent-bound chat 502'd with "Request URL is missing an 'http://' or 'https://' protocol".
4. **`028064a`** — history: `ChatMessage.created_at` → `.timestamp`; 3 endpoints (mark-stopped, update-last-meta, merge-last-assistant) 500'd unconditionally.
5. **`7789aa1`** — presets: 400 (not 500) on malformed JSON to `/api/presets/groups`.
6. **`8975b00`** — skills: reject SKILL.md without frontmatter on `/api/skills/{id}/markdown` (was silently renaming the skill to "skill" — data-corrupting).
7. **`b710221`** — app: internal-tool auth bypass no longer swallows downstream handler errors; `/backgrounds` 404s cleanly when absent.
8. **`1dc3c8b`** — cookbook: `/api/cookbook/setup` ssh quoting collision (`shlex.quote`) + false-positive `ok:true`.
9. **`abcc7cd`** — documents: 503 (not 500) when PyMuPDF missing on `export-pdf`/`render-pdf` (graceful-degradation consistency).
10. **`58a3e2e`** — hwfit/email: 400 (not 500) on non-numeric `gpu_count` / `*_port` query+body params.
11. **`0288f3c`** — email: guard remaining port `int()` parses (account create/update/test-connection).
12. **`331aa09`** — cookbook: env-less `/api/cookbook/state` syncs no longer dropped once an hfToken is stored (anti-wipe guard re-validated the encrypted token and discarded the write).

## Recommendations

_(collected during audit, finalized in Phase 4)_

## Endpoint scoreboard

**436 endpoints — 393 PASS · 43 BLOCKED (justified) · 0 FAIL** (full per-endpoint detail in AUDIT/ENDPOINTS.md; machine-readable source in AUDIT/endpoints_state.json)

| Class | PASS | BLOCKED | Notes |
|-------|-----:|--------:|-------|
| NORMAL | 273 | 1 | the 1 BLOCKED is the shadowed dead route `GET /api/history/{id}` |
| ADMIN | 74 | 0 | all admin-gated routes exercised with the admin cookie |
| LLM | 24 | 4 | BLOCKED = need vision (sidecar has none) or email creds |
| LONG-RUNNING | 8 | 3 | research/model-download/serve/probe all run; image-AI ops need optional deps |
| EXTERNAL-CREDS | 4 | 34 | no IMAP/SMTP/CalDAV/HF/paid keys on this box → all degrade gracefully |
| DESTRUCTIVE | 7 | 1 | run last against expendable data; BLOCKED = email reminders (no IMAP) |
| INTERNAL | 3 | 0 | service-to-service; tested via X-Odysseus-Internal-Token on loopback |

BLOCKED reasons: 37 no-creds-graceful (EXTERNAL-CREDS, clean error/empty result) · 3 optional-dep-graceful (realesrgan/rembg not installed — clear "install X" message) · 2 no-vision-graceful (sidecar has no vision, quirk d) · 1 shadowed-dead-route (documented). Every BLOCKED was verified to return a clean 4xx / 200-with-error / 503 — no 500s, no hangs, no tracebacks.

Known-quirk endpoints (verified graceful, not "fixed"): (a) `POST /api/tasks/{id}/webhook/{token}` — auth middleware intercepts external callers (401); works from a logged-in/localhost context. (b) API-only admin features with no wired UI: API tokens, outgoing webhooks, feature toggles, RAG upload — API surface tested, no UI in this build. (c) MCP one-click presets are dead code; the generic add form is the live path. (d) sidecar has no vision — image input degrades to "[No vision model configured]".

## Recommendations for smoother Odysseus installs

1. **Ship the sidecar against the current `claude` CLI.** The headline subscription feature 500'd on every non-streaming call because the CLI now emits a JSON *array* for `--output-format json` (the code's own docstring pinned it to an older v2.1.161). Add a CLI-version check at `register_endpoint.py` time, and a tiny self-test (`POST /v1/chat/completions {stream:false}`) in `claude_sidecar/run.sh` startup so drift is caught immediately, not at first chat. (fixed: 9b8061c)
2. **Make the model probe tolerant of CLI-spawn latency.** The sidecar spawns a fresh `claude` per completion (~8–10s cold start); the probe's hardcoded 8s timeout marked all its models failed and then *persisted* them into `hidden_models`, silently hiding the subscription endpoint from every model picker. Probe timeout is now `ODYSSEUS_PROBE_TIMEOUT` (30s default), and a self-inflicted hide is the worst failure mode for a probe — consider never auto-persisting hides from a single timeout. (fixed: 1d7f660)
3. **Bundle/auto-start ChromaDB on the native path.** `start-macos.sh` installs only the Chroma HTTP *client* and the app expects a server on :8100; the first run logs a retrying warning forever. Either start a `docker run chromadb/chroma` when Docker is present, or print the exact one-liner in the warning. (env workaround applied)
4. **PyMuPDF is effectively required, not optional.** Five document endpoints are dead without it; two of them used to 500 instead of degrading. Either move PyMuPDF into `requirements.txt`, or keep it optional but make every PDF route degrade to a consistent 503 (done: abcc7cd) and grey out the PDF UI when absent.
5. **Guard `await request.json()` everywhere.** Several POST handlers parse the body with no try/except, turning a malformed request into a 500 + traceback (`/api/presets/groups` was one; audit only fixed the reported case). A shared dependency that returns a clean 400 would remove a whole bug class.
6. **Treat "save" endpoints as never-destructive on bad input.** `/api/skills/{id}/markdown` renamed/moved a skill on disk when given garbage because `parse_frontmatter` returns `({}, text)` instead of raising. Validate before mutating. (fixed: 8975b00)
7. **Don't let auth-middleware bypasses swallow handler errors.** The internal-tool bypass wrapped `call_next` in `try/except: pass`, masking real 4xx/5xx across the whole internal-tool surface as a login redirect. Keep guards around credential checks only, never around the downstream call. (fixed: b710221)
8. **Tidy two cosmetics:** generic OS-error strings leak to users (`[Errno 61] Connection refused`, "Mail operation failed") where "no email account configured" would be clearer; and `model_info` streams an empty model name on the claude_code path before the engine resolves its default.

## Convergence pass 3 — 1 new bug found & fixed

Pass 3 (24/27 batches; 3 agents died on harness socket errors — infrastructure, not app — their 18 endpoints re-covered in pass 4): **1 new FAIL**.

### P12 — `POST /api/cookbook/state` silently drops env-less writes once an hfToken is stored
- **Symptom:** with an hfToken saved, any POST without a top-level `env` key → `{"ok":false,"error":"400: Invalid token characters"}` and the state write is silently discarded — exactly the debounced env-less syncs the route's anti-wipe guard exists to protect.
- **Root cause:** the anti-wipe guard re-injects the on-disk env (holding the already-encrypted `enc:gAAAA…` token) into the incoming body; `_state_for_storage` then treats that ciphertext as a *fresh* token and `_validate_token` rejects its `:`/base64 characters; the outer try/except converts the 400 into `ok:false` and the write is dropped.
- **Fix:** `331aa09` — skip re-validation/re-encryption when the incoming token already carries the `enc:` sentinel. Verified against the exact poisoned on-disk state the fleet agent left behind: env-less POST → `{"ok":true}`, write persists, token ciphertext intact.
- **Verdict:** ODYSSEUS BUG (state-loss; the guard defeated its own purpose).

## Allowance pause (logged per mission ground rules)
- 2026-06-10 ~18:50 CEST: convergence pass 4 aborted — the audit harness's own Claude subscription hit its session limit ("You've hit your session limit · resets 7pm Europe/Madrid"); 24/27 fleet agents died mid-batch. The 3 batches that completed (admin-misc, app-root, +partial) were all-PASS. Limit reset confirmed 19:06 CEST (`claude -p` answers again); pass 4 relaunched as a leaner verification fleet. The app itself never misbehaved during the window — this was harness-side, not an Odysseus issue.
