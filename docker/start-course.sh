#!/bin/bash
# Starts both the Claude sidecar and Odysseus together inside the container.
set -e

cd /app

echo "================================================"
echo "  Odysseus Course Environment"
echo "================================================"

# Verify Claude Code is authenticated before starting
if ! claude --version >/dev/null 2>&1; then
    echo ""
    echo "ERROR: Claude Code is not installed correctly."
    echo "Please rebuild the image: docker compose -f docker-compose.course.yml build"
    exit 1
fi

# Subscription-only: authenticate via `claude auth login` (writes the
# credentials file). We deliberately do NOT accept ANTHROPIC_API_KEY here —
# Odysseus must stay on the Claude subscription, never pay-as-you-go API.
if [ ! -f /root/.claude/.credentials.json ]; then
    echo ""
    echo "ERROR: Claude is not authenticated."
    echo "Run this once in a separate terminal to log in:"
    echo ""
    echo "  docker exec -it odysseus-course claude auth login"
    echo ""
    echo "Then restart: docker compose -f docker-compose.course.yml restart"
    exit 1
fi

# Start the sidecar in background (run.sh has its own restart loop)
echo "Starting Claude sidecar on port 8750..."
./claude_sidecar/run.sh &

# Give the sidecar a moment to bind its port
sleep 4

echo "Starting Odysseus on http://localhost:7860 ..."
echo ""
exec ./venv/bin/uvicorn app:app --host 0.0.0.0 --port 7860
