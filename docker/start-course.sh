#!/bin/bash
# Starts both the Claude sidecar and Odysseus together inside the container.
set -e

cd /app

echo "================================================"
echo "  Odysseus Course Environment"
echo "================================================"

# Verify Claude Code is installed
if ! claude --version >/dev/null 2>&1; then
    echo ""
    echo "ERROR: Claude Code is not installed correctly."
    echo "Please rebuild the image: docker compose -f docker-compose.course.yml build"
    exit 1
fi

# Wait for Claude login if not yet authenticated.
# Subscription-only: we authenticate via `claude auth login` (credentials file).
# We deliberately do NOT accept ANTHROPIC_API_KEY — Odysseus must stay on the
# Claude subscription, never pay-as-you-go API.
if [ ! -f /root/.claude/.credentials.json ]; then
    echo ""
    echo "  Claude is not logged in yet."
    echo ""
    echo "  Open a NEW terminal window and run:"
    echo ""
    echo "    docker exec -it odysseus-course claude auth login"
    echo ""
    echo "  Follow the link, log in with your Claude account,"
    echo "  then paste the code back in that terminal."
    echo ""
    echo "  Waiting for login..."
    echo ""
    while [ ! -f /root/.claude/.credentials.json ]; do
        sleep 3
    done
    echo "  Login detected! Starting Odysseus..."
    echo ""
fi

# Seed database: model endpoint + default student account
./venv/bin/python - <<'PYEOF'
import sys, os, datetime, json, time
sys.path.insert(0, '/app')
os.makedirs('/app/data', exist_ok=True)

try:
    from core.database import SessionLocal, Base, engine, ModelEndpoint
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if not db.query(ModelEndpoint).filter_by(id="claude-cli-sidecar").first():
            now = datetime.datetime.utcnow()
            db.add(ModelEndpoint(
                id="claude-cli-sidecar",
                name="Claude (Subscription)",
                base_url="http://127.0.0.1:8750/v1",
                api_key="",
                is_enabled=True,
                cached_models='["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"]',
                supports_tools=True,
                created_at=now,
                updated_at=now,
            ))
            db.commit()
            print("  Claude model endpoint configured.")
    finally:
        db.close()
except Exception as e:
    print(f"  Warning: could not seed model endpoint: {e}")

# Create default student login on first run (only if auth.json doesn't exist yet)
auth_path = '/app/data/auth.json'
if not os.path.exists(auth_path):
    try:
        import bcrypt
        hashed = bcrypt.hashpw(b'odysseus', bcrypt.gensalt()).decode()
        auth_data = {
            "users": {
                "student": {
                    "password_hash": hashed,
                    "is_admin": True,
                    "created": time.time(),
                    "privileges": {
                        "can_use_agent": True,
                        "can_use_browser": True,
                        "can_use_bash": True,
                        "can_use_documents": True,
                        "can_use_research": True,
                        "can_generate_images": True,
                        "can_manage_memory": True,
                        "max_messages_per_day": 0,
                        "allowed_models": []
                    }
                }
            }
        }
        with open(auth_path, 'w') as f:
            json.dump(auth_data, f, indent=2)
        print("  Default account created: student / odysseus")
        print("  (Change your password in Settings after logging in)")
    except Exception as e:
        print(f"  Warning: could not create default account: {e}")
else:
    print("  Account already exists — skipping default user seed.")
PYEOF

# Start the sidecar in background (run.sh has its own restart loop)
echo "Starting Claude sidecar on port 8750..."
./claude_sidecar/run.sh &

# Give the sidecar a moment to bind its port
sleep 4

echo "Starting Odysseus on http://localhost:7860 ..."
echo "  Login: student / odysseus"
echo ""
exec ./venv/bin/uvicorn app:app --host 0.0.0.0 --port 7860
