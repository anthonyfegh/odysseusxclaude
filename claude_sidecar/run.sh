#!/bin/bash
# Supervised launcher for the Claude CLI sidecar.
# Binds 127.0.0.1:8750 by default; auto-restarts so Odysseus never sees a
# connection refusal (which would trip the 20s dead-host cooldown).
#
#   ./claude_sidecar/run.sh
#
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export CLAUDE_SIDECAR_PORT="${CLAUDE_SIDECAR_PORT:-8750}"
export CLAUDE_SIDECAR_DEFAULT_MODEL="${CLAUDE_SIDECAR_DEFAULT_MODEL:-claude-sonnet-4-6}"
# Drop WebSearch/WebFetch from the sidecar's native fallback tools so plain /
# unbound chats (which run here, not on the agent engine) cannot browse the web.
# Web search then only happens through an agent that has the web_search tool
# toggled on, running on the claude_code engine. Keeps cheap chats web-free.
export CLAUDE_SIDECAR_NATIVE_TOOLS="${CLAUDE_SIDECAR_NATIVE_TOOLS:-Read,Glob,Grep}"

# Optional behaviour knobs (defaults are sensible; override only if you need to):
#   CLAUDE_SIDECAR_NATIVE_TOOLS  Claude's own native tools enabled as a read-only
#       fallback. Default "Read,Glob,Grep,WebSearch,WebFetch,Skill". Set to "" for
#       the old pure-reasoning mode (Odysseus owns every tool, Claude has none).
#   CLAUDE_SIDECAR_PREAMBLE      "1" (default) prepends the Odysseus runtime preamble
#       (identity + tool priority + host-plugin-leak neutralisation). "0" disables it.

# Absolute path to the `claude` CLI. Auto-detected from your PATH (works for any
# install: npm global, the official installer, nvm). Override CLAUDE_BIN only if
# yours lives somewhere unusual.
if [ -z "${CLAUDE_BIN:-}" ]; then
  CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
fi
export CLAUDE_BIN

if [ -z "$CLAUDE_BIN" ] || [ ! -x "$CLAUDE_BIN" ]; then
  echo "✗ The 'claude' CLI was not found. Install Claude Code (https://claude.com/claude-code)" >&2
  echo "  and sign in, then re-run. If it's installed somewhere unusual, point us at it:" >&2
  echo "    CLAUDE_BIN=\"\$(which claude)\" ./claude_sidecar/run.sh" >&2
  exit 1
fi

echo "▶ Claude sidecar on http://127.0.0.1:${CLAUDE_SIDECAR_PORT}/v1  (claude=${CLAUDE_BIN})"
echo "  Ctrl+C to stop."
while true; do
  ./venv/bin/python claude_sidecar/sidecar.py
  code=$?
  [ $code -eq 130 ] && break   # Ctrl+C
  echo "✗ sidecar exited ($code) — restarting in 2s…" >&2
  sleep 2
done
