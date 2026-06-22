# Odysseus — Setup Guide (from zero)

Your own AI-agent workspace, running entirely on your computer, powered by **your
Claude subscription** (no separate API key or billing). About 15 minutes start to finish.

---

## Before you start — you need two things

1. **A Claude subscription** (Pro or Max). The AI runs on your subscription via
   `claude auth login`. There is no pay-as-you-go API key anywhere.
2. **A computer with ~3 GB free disk** (Mac, Windows, or Linux).

---

## Step 1 — Install Docker Desktop

- Download: <https://www.docker.com/products/docker-desktop/>
  (on a Mac you can also run `brew install --cask docker`)
- Open **Docker Desktop** and wait until the whale icon says **"Docker Desktop is running."**

You never type Docker commands into Docker Desktop — it just needs to be running in the
background. You'll use your normal Terminal for the steps below.

---

## Step 2 — Create your class folder + the compose file

Make a folder for the class and put one file in it:

```bash
mkdir -p ~/odysseus-class
cd ~/odysseus-class
```

Create a file named **`docker-compose.student.yml`** in that folder with exactly this
(or use the file your instructor shared):

```yaml
services:
  odysseus:
    container_name: odysseus-course
    image: anthonydocker123/odysseus-course:latest
    ports:
      - "7860:7860"
    volumes:
      # Your data — agents, memory, tasks, connector credentials (persists)
      - ./data:/app/data
      - ./logs:/app/logs
      # Your Claude login — persists between restarts after first login
      - ./claude-auth:/root/.claude
    restart: unless-stopped
```

---

## Step 3 — Start Odysseus

```bash
cd ~/odysseus-class
docker compose -f docker-compose.student.yml up -d
```

The first run downloads the image (~650 MB) — a few minutes, once.

---

## Step 4 — Log in to Claude (one time)

Watch the startup:

```bash
docker compose -f docker-compose.student.yml logs -f
```

You'll see:

```
  Claude is not logged in yet.
  Open a NEW terminal window and run:
      docker exec -it odysseus-course claude auth login
  Waiting for login...
```

Open a **new** Terminal window and run:

```bash
docker exec -it odysseus-course claude auth login
```

Follow the link, sign in with your **Claude account**, and paste the code back. The
container detects the login, sets up your account, and finishes starting. Press
**Ctrl-C** to stop watching the logs (that does *not* stop Odysseus).

---

## Step 5 — Open Odysseus

- Go to **<http://localhost:7860>** in your browser.
- Log in with: **`student`** / **`odysseus`**
- **Change your password** in Settings right away.

The AI model is already configured (your Claude subscription, via the built-in sidecar),
so you can start chatting immediately.

---

## Step 6 — Connect your tools

- **Email** — Settings → add your IMAP/SMTP account (e.g. Gmail: IMAP 993, SMTP 465).
- **Connectors** (Slack, Notion, Monday, Typeform, Miro, HeyGen, ElevenLabs, Holded) —
  Settings → **MCP** → add the connector and paste your API key for that service. Your
  agents can then use it.
- **Google Drive / Sheets / Slides** need an extra install step — ask your instructor
  (they require two optional Python packages not bundled by default).

---

## Everyday use

| Action | Command (run inside `~/odysseus-class`) |
|---|---|
| Stop (keeps all your data) | `docker compose -f docker-compose.student.yml down` |
| Start again | `docker compose -f docker-compose.student.yml up -d` |
| Get the newest version | `docker compose -f docker-compose.student.yml pull` then `… up -d` |
| See logs | `docker compose -f docker-compose.student.yml logs -f` |

Your data lives in `~/odysseus-class/data` and **persists across restarts and updates.**
Your Claude login persists in `~/odysseus-class/claude-auth` — you only log in once.

---

## If something breaks — you have a built-in fix-it assistant

A Claude Code assistant lives inside the container and knows how Odysseus is wired:

```bash
docker exec -it odysseus-course claude
```

Describe the problem (or paste an error/screenshot). It can read the logs, fix files,
and adjust the database for you, then confirm it worked.

---

## Troubleshooting

- **Stuck at "Waiting for login…"** → you haven't logged in yet. Run
  `docker exec -it odysseus-course claude auth login`.
- **"port is already allocated"** → something else is using port 7860 (maybe another
  Odysseus). Stop it, or change `"7860:7860"` to `"7870:7860"` in the compose file and
  open <http://localhost:7870> instead.
- **Nothing loads at localhost:7860** → check Docker Desktop is running and the
  container is up: `docker ps` (you should see `odysseus-course`).
- **Forgot your password / locked out** → ask the fix-it assistant (above) to reset it,
  or delete `~/odysseus-class/data/auth.json` and restart to get `student / odysseus`
  back (this only resets the login, not your agents/data).
- **Want a clean slate** → `docker compose -f docker-compose.student.yml down`, delete
  the `data/` folder, then `up -d` again.
