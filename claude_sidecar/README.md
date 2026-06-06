# Claude CLI sidecar for Odysseus

Use your **Claude subscription** (via the `claude -p` headless CLI) as a normal
Odysseus model endpoint, while **Odysseus keeps executing all of its own tools**.

Claude runs as a pure reasoning engine (`--tools ""`). Odysseus sends its tool
schemas in each request; the sidecar tells Claude how to emit a tool call and
translates Claude's reply into native OpenAI `tool_calls`, which Odysseus
dispatches through its normal pipeline (with owner/session/admin gating intact).

## Files
- `sidecar.py` — the OpenAI-compatible server (`/v1/models`, `/v1/chat/completions`).
- `run.sh` — supervised launcher (auto-restarts; binds `127.0.0.1:8750`).
- `register_endpoint.py` — adds/updates the Odysseus Model Endpoint row.

## One-time setup
1. **Turn OFF "Extra Usage"** so calls only use your subscription, never
   pay-as-you-go credits: in Claude Code run `/usage-credits` (or claude.ai →
   Settings → Billing) and disable it. When the included allowance is exhausted,
   the sidecar returns a clean 429 instead of charging credits.
2. **Register the endpoint** (already done once; safe to re-run):
   ```bash
   ./venv/bin/python claude_sidecar/register_endpoint.py
   ```

## Run
Start the sidecar (keep this running while you use Odysseus):
```bash
./claude_sidecar/run.sh
```
Then in Odysseus **Settings → Models**: pick a **Claude CLI (subscription)** model.

## Model guidance (important)
- **Agent mode → use Sonnet or Opus.** They reliably follow the tool-call format.
  **Haiku is too weak for tools** (it tends to say a tool is "unavailable") — use
  it only for plain chat.
- Set Odysseus's **utility/title/compaction/task/research** models to a **cheap**
  model (Haiku, or a local Ollama model) so background work doesn't spend your
  Claude allowance. Otherwise every auto-title and compaction spawns Claude.
- The default model is Sonnet (`CLAUDE_SIDECAR_DEFAULT_MODEL`).

## How it routes (correctness notes)
- Every advertised model id contains the literal substring **`claude`** — this is
  what makes Odysseus send tool schemas (`_is_api_model=True`). Do not rename them
  to drop `claude`, or tools silently stop working.
- Base URL must be `http://127.0.0.1:<port>/v1` (never `/api`, never port 11434),
  or Odysseus would misroute it to the Ollama provider branch.
- Auth: uses your subscription/OAuth (`~/.claude`); the sidecar does **not** use
  `--bare` (which would force an API key). No `ANTHROPIC_API_KEY` needed.

## Env knobs
| Var | Default | Meaning |
|---|---|---|
| `CLAUDE_SIDECAR_PORT` | `8750` | listen port |
| `CLAUDE_BIN` | nvm path | absolute path to the `claude` CLI |
| `CLAUDE_SIDECAR_DEFAULT_MODEL` | `claude-sonnet-4-6` | model when a request omits one |
| `CLAUDE_SIDECAR_CONCURRENCY` | `4` | max concurrent `claude` subprocesses |
| `CLAUDE_SIDECAR_FIRST_TOKEN_TIMEOUT` | `90` | seconds to first token before failing pre-content |
| `CLAUDE_SIDECAR_CWD` | `/tmp/odysseus-claude-sidecar` | fixed scratch cwd for claude sessions |

## Status / not yet implemented
- v1 (done): chat, agent tools via native `tool_calls`, streaming + non-streaming,
  subprocess kill on disconnect, pre-content failures → HTTP non-200, subscription
  billing.
- Not yet: the **session manager** (`--session-id`/`--resume` reuse) and **vision**
  (image input). Vision currently degrades to a text placeholder — route image
  tasks to a separate vision endpoint for now. `vault_*` / `generate_image` remain
  pre-existing Odysseus dispatch gaps (see the plan's optional core patches).
