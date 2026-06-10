"""Merge test-result JSONs into AUDIT/endpoints_state.json and re-render ENDPOINTS.md.

Usage: python3 AUDIT/tools/merge_results.py result_file.json [more.json ...]
Each input: {"results": [{method, path, status, evidence, reason?, diagnosis?}, ...]}
or the round-1 workflow shape {"result": {"batches": [{results: [...]}, ...]}}.
Status mapping: PASS -> PASS, FAIL -> FAIL, BLOCKED -> BLOCKED(reason).
"""
import json
import os
import subprocess
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
state_path = os.path.join(root, "AUDIT", "endpoints_state.json")
state = json.load(open(state_path))
index = {(e["method"].upper(), e["path"]): e for e in state["endpoints"]}

applied, unmatched = 0, []
for arg in sys.argv[1:]:
    data = json.load(open(arg))
    if "result" in data and isinstance(data["result"], dict):
        results = [r for b in data["result"].get("batches", []) for r in (b.get("results") or [])]
    elif "batches" in data:
        results = [r for b in data.get("batches", []) for r in (b.get("results") or [])]
    else:
        results = data.get("results", [])
    for r in results:
        key = (r["method"].upper(), r["path"])
        e = index.get(key)
        if not e:
            unmatched.append(key)
            continue
        status = r["status"].upper()
        if status == "BLOCKED" and r.get("reason"):
            status = f"BLOCKED({r['reason']})"
        e["status"] = status
        note = r.get("evidence", "")
        if r.get("diagnosis"):
            note += f" | DIAG: {r['diagnosis']}"
        e["result"] = note
        applied += 1

json.dump(state, open(state_path, "w"), indent=1)
print(f"applied {applied} results; unmatched: {unmatched if unmatched else 'none'}")
subprocess.run([sys.executable, os.path.join(root, "AUDIT", "tools", "render_endpoints.py")], check=True)
