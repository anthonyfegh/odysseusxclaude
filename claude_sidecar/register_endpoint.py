#!/usr/bin/env python3
"""Register (or update) the Claude CLI sidecar as an Odysseus Model Endpoint.

Run with the Odysseus venv from the repo root:
    ./venv/bin/python claude_sidecar/register_endpoint.py
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal, ModelEndpoint  # noqa: E402

ENDPOINT_ID = "claude-cli-sidecar"
BASE_URL = os.environ.get("CLAUDE_SIDECAR_BASE_URL", "http://127.0.0.1:8750/v1")
MODELS = ["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5"]

db = SessionLocal()
try:
    ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ENDPOINT_ID).first()
    if ep is None:
        ep = ModelEndpoint(id=ENDPOINT_ID)
        db.add(ep)
    ep.name = "Claude CLI (subscription)"
    ep.base_url = BASE_URL
    ep.api_key = None
    ep.is_enabled = True
    ep.model_type = "llm"
    ep.supports_tools = True  # harmless; the "claude" name also drives _is_api_model
    ep.cached_models = json.dumps(MODELS)
    ep.hidden_models = json.dumps([])
    ep.owner = None  # shared / visible to all users
    db.commit()
    print(f"[ok] Registered endpoint '{ep.name}' id={ENDPOINT_ID}")
    print(f"     base_url={BASE_URL}")
    print(f"     models={MODELS}")
finally:
    db.close()
