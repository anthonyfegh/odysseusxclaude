# Odysseus

> Your own private AI workspace — runs on **your** computer, thinks with **your Claude subscription**, and keeps **your** data with you.

![Odysseus](docs/odysseus.jpg)

Chat, agents that actually do the work, deep research, documents, email, calendar, notes & tasks — all in one place, all yours. No API keys and **no per-message charges**: Odysseus runs on the Claude plan you already pay for, through Anthropic's official **Claude Code** (`claude`).

A few of the things it does:

- **Chat** with Claude (or any local model you add).
- **Agents** — give one a job and it runs the whole task itself, using web search, files, documents, and more. Each agent has its own **Workspace** where you can watch it work live and see everything it makes.
- **Self-improving tasks** — schedule a task; if it ever stumbles, a smarter Claude (Opus) steps in, finishes the job, and remembers how to do it better next time.
- **Deep Research**, **Documents**, **Email**, **Calendar**, **Notes & Tasks**, **Memory** — the everyday tools, built in.
- **Works on your phone** too, on your own Wi‑Fi.

Everything lives in a `data/` folder on your machine — nothing goes to the cloud.

---

## What you'll need

- A **Mac** (Apple Silicon — M1/M2/M3/M4 — recommended) or a **Linux** computer.
- A **Claude subscription** (Pro or Max). This is the brain.
- About **15 minutes** for the one‑time setup. After that, starting it is two clicks.

You do **not** need: an OpenAI key, an Anthropic API key, Docker, or any coding experience.

---

## Setup (one time)

### Step 1 — Install Claude Code and sign in

Claude Code is Anthropic's official app that lets your computer talk to Claude.

1. Install it from **https://claude.com/claude-code** (follow their short instructions).
2. Open the **Terminal** app, type `claude`, and press **Enter**. The first time, it asks you to sign in — use the **same account as your Claude subscription**.
3. Once you can chat with `claude` in the Terminal, you're good. (Type `/exit` to leave it.)

> 💡 So Odysseus only ever uses your subscription (and never rings up surprise charges), turn **Extra Usage / pay‑as‑you‑go OFF**: in Claude Code type `/usage-credits`, or on claude.ai go to **Settings → Billing**. When your monthly allowance runs out, Odysseus simply pauses instead of charging you.

### Step 2 — Get Odysseus

Download this project. If you have Git:

```bash
git clone https://github.com/YOUR-USERNAME/odysseus.git
cd odysseus
```

*(Replace the link with this repository's address. No Git? Click the green **Code → Download ZIP** button on the project page, unzip it, then open that folder in Terminal.)*

### Step 3 — Start Odysseus

In Terminal, inside the `odysseus` folder, run:

```bash
./start-macos.sh
```

The first run installs everything it needs (a few minutes), then launches Odysseus. It will:

- open Odysseus in your browser at **http://127.0.0.1:7860**, and
- print your login in the Terminal — an **admin username** and a **temporary password**. **Copy those down.**

Keep this Terminal window open while you use Odysseus. (Press **Ctrl+C** here to stop it later.)

> **On Linux**, instead of `./start-macos.sh`, run these once:
> ```bash
> python3 -m venv venv && source venv/bin/activate
> pip install -r requirements.txt
> python setup.py            # prints your admin username + temporary password
> python -m uvicorn app:app --host 127.0.0.1 --port 7860
> ```

### Step 4 — Connect your Claude subscription (the "sidecar")

This little helper is what routes Odysseus through `claude -p` so it uses your plan.

Open a **second** Terminal window, go to the same `odysseus` folder, and:

1. **One time**, register the connection:
   ```bash
   ./venv/bin/python claude_sidecar/register_endpoint.py
   ```
2. **Start it** (keep this window open whenever you use Odysseus):
   ```bash
   ./claude_sidecar/run.sh
   ```

You should see `▶ Claude sidecar on http://127.0.0.1:8750`. Leave it running.

### Step 5 — Log in and pick Claude

1. In your browser, open **http://127.0.0.1:7860** (it may already be open).
2. Log in with the **admin username + temporary password** from Step 3. You can change the password later in **Settings**.
3. Go to **Settings → Models** and choose a **“Claude CLI (subscription)”** model:
   - **Sonnet** — a great everyday default.
   - **Opus** — the most capable, for the hardest jobs.

🎉 Done — Odysseus is now thinking with your Claude subscription.

---

## Using it day to day

You don't repeat the setup. Each time you want Odysseus, open **two** Terminal windows in the `odysseus` folder:

| Window | Command | What it is |
|---|---|---|
| 1 | `./claude_sidecar/run.sh` | the Claude connection (keep it open) |
| 2 | `./start-macos.sh` | Odysseus itself |

Then open **http://127.0.0.1:7860**. When you're finished, press **Ctrl+C** in each window to stop.

---

## Good to know

- **Keep both windows open while using Odysseus.** If the sidecar (Window 1) is closed, the AI can't think.
- **Your data stays on your computer** — chats, documents, files, and settings live in the `data/` folder, never the cloud.
- **Use it from your phone** on the same Wi‑Fi by opening your computer's address (e.g. `http://192.168.1.50:7860`). Only do this on a network you trust — Odysseus is a powerful admin tool, so don't expose it to the open internet.

---

## If something isn't working

- **“The 'claude' CLI was not found”** when starting the sidecar → Step 1 didn't finish. Make sure typing `claude` in Terminal opens Claude. If it's installed somewhere unusual, point the sidecar at it:
  ```bash
  CLAUDE_BIN="$(which claude)" ./claude_sidecar/run.sh
  ```
- **The AI says a tool is “unavailable,” or replies are empty** → check that the **sidecar window is still running**, and that you picked a **“Claude CLI (subscription)”** model in **Settings → Models** (try Sonnet or Opus).
- **“Port already in use”** → something is already running there. Close the old window, or start on a different port:
  ```bash
  ODYSSEUS_PORT=7900 ./start-macos.sh
  ```
- **Forgot the admin password** → it was printed in the Terminal the first time you ran setup. Scroll up in that window to find it.

---

## License

MIT — see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).

```
                                  |
                                 |||
                                |||||
                  |    |    |   |||||||
                 )_)  )_)  )_)   ~|~
                )___))___))___)\  |
               )____)____)_____)\\|
             _____|____|____|_____\\\__
             \                       /
       ~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~
               ~^~  all aboard!  ~^~
       ~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~
```
