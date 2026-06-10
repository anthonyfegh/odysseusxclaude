"""Render AUDIT/ENDPOINTS.md from AUDIT/endpoints_state.json (source of truth).

Run from repo root:  python3 AUDIT/tools/render_endpoints.py
"""
import json
import os
from collections import Counter

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
state_path = os.path.join(root, "AUDIT", "endpoints_state.json")
out_path = os.path.join(root, "AUDIT", "ENDPOINTS.md")

d = json.load(open(state_path))
eps = d["endpoints"]
counts = Counter(e["status"].split("(")[0] for e in eps)

lines = [
    "# Odysseus Endpoint Checklist",
    "",
    "Statuses: UNTESTED · PASS · FAIL · BLOCKED(reason) · DEFERRED-DESTRUCTIVE",
    "Classes: NORMAL · ADMIN · LLM · LONG-RUNNING · EXTERNAL-CREDS · DESTRUCTIVE · INTERNAL",
    "",
    f"**{len(eps)} endpoints** — " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
    "",
    "Source of truth: `AUDIT/endpoints_state.json` (regenerate this file with `python3 AUDIT/tools/render_endpoints.py`).",
    "",
    "| Method | Path | Purpose | Class | Status | Notes |",
    "|--------|------|---------|-------|--------|-------|",
]


def esc(s):
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


for e in eps:
    note = e.get("result") or ""
    if e["server"] == "sidecar":
        note = ("[sidecar :8750] " + note).strip()
    lines.append(
        f"| {e['method']} | {esc(e['path'])} | {esc(e['purpose'])[:110]} | {e['class']} | {e['status']} | {esc(note)[:160]} |"
    )

open(out_path, "w").write("\n".join(lines) + "\n")
print(f"Wrote {out_path}: {len(eps)} endpoints — {dict(counts)}")
