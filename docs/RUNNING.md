# How to Run LocalLens on Your Machine

A complete beginner's guide. Two ways to run the app:

- **Option A — Local install** (most reliable; you run the backend and frontend yourself)
- **Option B — Docker** (one command to start everything; needs Docker Desktop)

Pick **Option A** if this is your first time. Pick **Option B** if you already have Docker Desktop running.

---

## What LocalLens does

You type a question like _"Find me the best 3 sushi restaurants near me"_ and the app talks to its AI brain (Groq), searches OpenStreetMap and the web, scores the results, writes a short summary for each, and shows them to you in a chat interface.

---

## Step 0 — Things you need to install first

You only have to do these once on your computer.

### On macOS

Open the **Terminal** app (press `Cmd + Space`, type "Terminal", press Enter), then paste each block and press Enter.

**1. Install Homebrew** (a tool that installs other tools — if you don't already have it):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**2. Install Python, Node.js, and ffmpeg** (the voice-input feature needs ffmpeg):

```bash
brew install python@3.11 node ffmpeg
```

**3. Check they all installed correctly:**

```bash
python3 --version       # should say Python 3.11.x or newer
node --version          # should say v18 or newer
ffmpeg -version         # should print version info
```

### On Windows

1. Download and install **Python 3.11+** from <https://www.python.org/downloads/> (during install, tick _"Add Python to PATH"_)
2. Download and install **Node.js 18+** from <https://nodejs.org/>
3. Download **ffmpeg** from <https://ffmpeg.org/download.html#build-windows> and add it to your PATH (only needed if you want voice input)
4. Open **PowerShell** (Start menu → search "PowerShell") and run the same checks:

```powershell
python --version
node --version
ffmpeg -version
```

### On Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip nodejs npm ffmpeg
```

---

## Step 1 — Get a free Groq API key (takes 2 minutes)

LocalLens uses Groq's free tier as its AI engine. **No credit card required.**

1. Open <https://console.groq.com> in your browser
2. Click _Sign Up_ (use Google or GitHub login)
3. Once logged in, click **API Keys** in the left menu
4. Click **Create API Key**, give it any name (e.g. "locallens"), copy the key — it looks like `gsk_AbC123...`
5. **Save that key somewhere** — you'll paste it into the app's config in the next step

---

## Step 2 — Get the code onto your computer

In Terminal / PowerShell, navigate to where you want to keep the project (e.g. your Desktop):

```bash
cd ~/Desktop
```

If you were given a zip file, unzip it here. If you have a Git URL, run:

```bash
git clone <the-repo-url> LocalLens-claude
```

Then enter the project folder:

```bash
cd LocalLens-claude
```

You should now see folders called `backend`, `frontend`, `docs`, and a file called `docker-compose.yml`. Type `ls` (Mac/Linux) or `dir` (Windows) to verify.

---

# Option A — Run Locally (no Docker)

You'll start the **backend** in one Terminal window and the **frontend** in a second window. Both have to be running at the same time.

## A1. Set up the backend

### A1.1. Open Terminal window #1, enter the backend folder

```bash
cd ~/Desktop/LocalLens-claude/backend
```

### A1.2. Create an isolated Python environment

This keeps LocalLens's libraries separate from your other Python work so nothing breaks.

```bash
python3 -m venv venv
```

This creates a folder called `venv` inside `backend`.

> Important: LocalLens needs **Python 3.11 or newer**. If your Mac still points `python3` to Python 3.9, create the venv with Python 3.11 directly:
>
> ```bash
> /opt/homebrew/bin/python3.11 -m venv venv
> ```

### A1.3. Activate the environment

**macOS / Linux:**

```bash
source venv/bin/activate
```

**Windows PowerShell:**

```powershell
.\venv\Scripts\Activate.ps1
```

You'll see `(venv)` appear at the start of your prompt — that means it worked.

> If Windows blocks the script with a security error, run:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
> then try again.

Check that the activated environment is using Python 3.11 or newer:

```bash
python --version
python -m pip --version
```

If `python --version` says Python 3.9 or older, delete or rename the venv and recreate it with Python 3.11:

```bash
deactivate 2>/dev/null || true
mv venv venv-old
/opt/homebrew/bin/python3.11 -m venv venv
source venv/bin/activate
python --version
```

### A1.4. Install Python packages

```bash
python -m pip install --upgrade pip
python -m pip install "setuptools==80.9.0" wheel
python -m pip install -r requirements.txt
```

This downloads about 4 GB of libraries (it includes machine-learning models). **It will take 5–15 minutes** on the first run. Get a coffee.

> If `torch` fails to install, run this one separately first:
> `pip install torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu`

### A1.5. Install the browser that the web-scraper uses

```bash
playwright install chromium
```

This downloads a small Chromium browser (~150 MB) that LocalLens uses to scrape Google Maps for reviews.

### A1.6. Create your config file

Copy the example config to a real one:

**macOS / Linux:**

```bash
cp .env.example .env
```

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
```

Now open `.env` in any text editor (TextEdit on Mac, Notepad on Windows, or your IDE). Find the line that says:

```
GROQ_API_KEY=
```

Paste your Groq key (from Step 1) after the `=`. It should look like:

```
GROQ_API_KEY=gsk_AbC123YourActualKeyHere
```

Save the file and close it.

### A1.7. Start the backend

Still in the `backend` folder with `(venv)` showing in your prompt:

```bash
uvicorn app.main:app --reload --port 8000
```

You should see log lines and finally a line like:

```
Uvicorn running on http://0.0.0.0:8000
```

**Leave this Terminal window open and running.** Closing it stops the backend.

> Quick test: in another browser tab, open <http://localhost:8000/health> — you should see `{"status":"ok",...}`.

---

## A2. Set up the frontend

### A2.1. Open a SECOND Terminal window

Keep the first one (backend) running. Open a new Terminal window (`Cmd+N` on Mac, or a new PowerShell on Windows).

### A2.2. Enter the frontend folder

```bash
cd ~/Desktop/LocalLens-claude/frontend
```

### A2.3. Install JavaScript packages

```bash
npm install
```

This downloads about 500 MB of Node packages. Takes 2–5 minutes on first run.

### A2.4. Start the frontend

```bash
npm run dev
```

You should see:

```
- Local:        http://localhost:3000
- ready in 2.1s
```

**Leave this Terminal window open too.**

---

## A3. Open the app

In your browser, go to:

**<http://localhost:3000>**

Type a question into the search box like:

> _"Best coffee shops near me"_

and press Enter. You should see the pipeline steps animate (Intent → Location → Search → Reviews → Scoring → Summary) and then results appear.

**You're done.** To shut everything down, switch to each Terminal window and press `Ctrl + C`.

---

# Option B — Run with Docker

Pick this if you already have **Docker Desktop** installed and running. If not, install it from <https://www.docker.com/products/docker-desktop/> and make sure the Docker whale icon is in your menu bar / system tray.

## B1. Create your config file

In a Terminal, go to the project root (the folder with `docker-compose.yml`):

```bash
cd ~/Desktop/LocalLens-claude
```

Then create a `.env` file in the project root (NOT in `backend/`):

**macOS / Linux:**

```bash
cat > .env <<'EOF'
LLM_PROVIDER=groq
LLM_MODEL=llama-3.1-70b-versatile
GROQ_API_KEY=paste-your-groq-key-here
EOF
```

**Windows PowerShell:**

```powershell
@"
LLM_PROVIDER=groq
LLM_MODEL=llama-3.1-70b-versatile
GROQ_API_KEY=paste-your-groq-key-here
"@ | Out-File -Encoding utf8 .env
```

Now open `.env` and replace `paste-your-groq-key-here` with your real Groq key.

## B2. Start everything

```bash
docker compose up --build
```

The first run will take **15–30 minutes** because Docker builds both the backend image (which includes all the ML libraries) and the frontend image. Subsequent runs are fast.

You'll see lots of log output. When you see something like:

```
backend-1  | Uvicorn running on http://0.0.0.0:8000
frontend-1 | ✓ Ready in 2s
```

…you're good to go.

## B3. Open the app

In your browser:

**<http://localhost:3000>**

## B4. Optional — also run Langfuse for observability

Langfuse shows you a trace of every step the AI takes. Useful for debugging.

In a second Terminal (keep the first running):

```bash
cd ~/Desktop/LocalLens-claude
docker compose --profile observability up langfuse-db langfuse-server
```

Open <http://localhost:3001> and sign up for a local account. Then:

1. Create a project, copy the _Public Key_ and _Secret Key_
2. Open `.env` and add these lines:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_HOST=http://langfuse-server:3000
   ```
3. Restart the backend: `docker compose restart backend`

## B5. Stop everything

In each running Terminal, press `Ctrl + C`. Then to fully remove the containers:

```bash
docker compose down
```

---

# How to use the app

1. **Type a question** in plain English, e.g.:
   - _"Best sushi restaurants near me"_
   - _"Top 5 coffee shops in downtown Austin"_
   - _"3 highly rated dentists near zip 10001"_
   - _"Yoga studios in Seattle open weekends"_

2. **Watch the pipeline.** As each step completes (Intent → Location → Search → Reviews → Scoring → Summary), the row turns green.

3. **Voice input** — click the microphone icon, speak your question, click again to stop. The text appears in the box; press Enter.

4. **Follow-ups** — after results appear, you can type things like:
   - _"show me cheaper ones"_
   - _"only ones open now"_
   - _"any others?"_
     LocalLens remembers the previous category and location.

5. **Clarifying questions** — if your query is too vague (e.g. _"find places"_), the app will ask back with clickable options.

---

# Troubleshooting

### `pip install` fails with "No module named 'pkg_resources'"

This usually happens while installing `openai-whisper`. Two common causes are:

- Your venv is using Python 3.9 instead of Python 3.11+
- Your `setuptools` version is too new and no longer provides `pkg_resources`

Run these commands from the `backend` folder:

```bash
cd ~/Desktop/LocalLens-claude/backend
source venv/bin/activate

python --version
python -m pip --version
```

If `python --version` says Python 3.9 or older, recreate the venv with Python 3.11:

```bash
deactivate 2>/dev/null || true
mv venv venv-py39-old

/opt/homebrew/bin/python3.11 -m venv venv
source venv/bin/activate
python --version
```

Then install the build tools and dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install "setuptools==80.9.0" wheel
python -c "import pkg_resources; print('pkg_resources ok')"

python -m pip install openai-whisper==20240930 --no-build-isolation
python -m pip install -r requirements.txt
```

Use `python -m pip` instead of plain `pip` so the command definitely uses the activated venv.

### "command not found: python3" or "command not found: node"

You didn't complete Step 0. Go back and install the prerequisites.

### "command not found: brew" (macOS)

Homebrew install didn't complete. Re-run the install command from Step 0.

### Backend says "GROQ_API_KEY missing"

You forgot to paste your key into `.env`. Open `backend/.env` (or `.env` in the project root for Docker) and make sure the line `GROQ_API_KEY=gsk_...` has your real key after the `=`.

### "Address already in use" on port 8000 or 3000

Something else is using that port. Either close that other thing, or change LocalLens's port:

- Backend: `uvicorn app.main:app --port 8001` (then in the frontend's `.env.local`, set `NEXT_PUBLIC_API_URL=http://localhost:8001`)

### `playwright install` fails or scraping is slow

Run `playwright install chromium --with-deps` to install system libraries.

### Frontend shows "Cannot connect to backend"

The backend isn't running, or it's running but on a different port. Make sure Terminal window #1 still shows `Uvicorn running on http://0.0.0.0:8000`.

### Docker build is taking forever

That's normal on the first build (15–30 minutes). The ML libraries are huge. Subsequent builds use the cached layers and take seconds.

### Voice input button does nothing

Your browser blocked microphone access. Look for the camera/mic icon in the address bar and allow microphone permission for `localhost`.

### I want to stop using ML features (just basic search)

Edit `backend/requirements.txt` and remove the lines for `torch`, `transformers`, `sentence-transformers`, `chromadb`, `openai-whisper`, and `playwright`. Then re-run `pip install -r requirements.txt`. LocalLens will gracefully fall back to keyword sentiment + DuckDuckGo + Overpass without these.

---

# Summary cheat sheet

**Run locally (recommended):**

```bash
# One-time setup
cd ~/Desktop/LocalLens-claude/backend
python3 -m venv venv
source venv/bin/activate          # or .\venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
playwright install chromium
cp .env.example .env              # then edit .env, paste your Groq key

cd ../frontend
npm install

# Every time you want to run:
# Terminal 1:
cd ~/Desktop/LocalLens-claude/backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2:
cd ~/Desktop/LocalLens-claude/frontend
npm run dev

# Then open http://localhost:3000
```

**Run with Docker:**

```bash
cd ~/Desktop/LocalLens-claude
# create .env in this folder with GROQ_API_KEY=...
docker compose up --build
# Then open http://localhost:3000
# Stop with Ctrl+C, then: docker compose down
```

**To Kill occupied port**

```bash
lsof -ti :8000 | xargs kill -9 2>/dev/null && echo "killed" || echo "nothing on 8000"
```
