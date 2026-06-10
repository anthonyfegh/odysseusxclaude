"""Dump every registered FastAPI route of the Odysseus app as JSON.

Run from the repo root:  ./venv/bin/python AUDIT/tools/dump_routes.py > AUDIT/routes_dump.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.routing import APIRoute, APIWebSocketRoute  # noqa: E402
from starlette.routing import Mount, Route  # noqa: E402

from app import app  # noqa: E402

routes = []
for r in app.routes:
    if isinstance(r, APIRoute):
        routes.append({
            "path": r.path,
            "methods": sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS")),
            "name": r.name,
            "kind": "api",
        })
    elif isinstance(r, APIWebSocketRoute):
        routes.append({"path": r.path, "methods": ["WEBSOCKET"], "name": r.name, "kind": "websocket"})
    elif isinstance(r, Mount):
        routes.append({"path": r.path, "methods": ["MOUNT"], "name": r.name, "kind": "mount"})
    elif isinstance(r, Route):
        routes.append({
            "path": r.path,
            "methods": sorted(m for m in (r.methods or []) if m not in ("HEAD", "OPTIONS")),
            "name": r.name,
            "kind": "route",
        })

routes.sort(key=lambda x: (x["path"], x["methods"]))
json.dump({"count": len(routes), "routes": routes}, sys.stdout, indent=1)
