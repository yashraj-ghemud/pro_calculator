# Pro Calculator + Voice AI (Hackathon Ready)

This project adds a voice-controlled layer to the Pro Calculator web app.

- Front-end: `index.html`, `styles.css`, `script.js`
- Voice backend (Python/FastAPI): `voice_service.py` + `ml/` (intent detection + expression normalizer)
- Trainer UI: `manual_trainer.py` for curating and retraining the model quickly

## Quick start (local demo)

1. Create env and install deps

```powershell
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
```

2. Train or refresh the intent model

```powershell
python -c "from ml.intent_classifier import IntentClassifier; IntentClassifier().retrain()"
```

3. Run the voice service

```powershell
uvicorn voice_service:app --host 127.0.0.1 --port 8000
```

4. Open the calculator (any static server is fine) and set the API base if needed

- Default is `http://127.0.0.1:8000` (in `script.js`). You can also use `config.js` (see below).

## Deploying the front-end

Host the static files (`index.html`, `styles.css`, `script.js`, `manifest.webmanifest`) on any static host (Netlify, GitHub Pages, S3+CloudFront, Vercel static).

If your voice backend runs on a different host, set the base URL used by the UI:

- Option A: Edit `script.js` constant `VOICE_API_BASE`
- Option B: Add `config.js` with `window.PROCALC_VOICE_API_BASE = "https://your-domain";` (see below)

## Deploying the voice backend (machine with microphone)

This service needs a real microphone. Options:

- Your laptop/mini PC near the demo booth
- A VM/edge device with a USB mic

### Systemd + Nginx (Ubuntu sample)

1) Copy files to the server and install Python 3.11+

```bash
python3 -m venv /opt/procalc/.venv
source /opt/procalc/.venv/bin/activate
pip install -r /opt/procalc/requirements.txt
python -c "from ml.intent_classifier import IntentClassifier; IntentClassifier().retrain()"
```

2) Create a systemd unit (see `deploy/systemd/procalc-voice.service`)

```bash
sudo systemctl daemon-reload
sudo systemctl enable procalc-voice
sudo systemctl start procalc-voice
```

3) Put Nginx in front (see `deploy/nginx.conf.sample`) and point a DNS name (e.g., voice.yourdomain.com)

4) In the front-end, set `VOICE_API_BASE` to `https://voice.yourdomain.com`

## Manual trainer

```powershell
python manual_trainer.py
```

- Press "Start listening", tick or correct the expression, then "Retrain model".
- To hot-reload the running service after retraining:

```powershell
Invoke-WebRequest -Method POST http://127.0.0.1:8000/voice/reload-model
```

## Config override (optional)

Create `config.js` in the project root with:

```js
window.PROCALC_VOICE_API_BASE = "https://voice.yourdomain.com";
```

Then include it in `index.html` before `script.js`:

```html
<script src="config.js"></script>
<script src="script.js" defer></script>
```

## Files

- `voice_service.py` — FastAPI app exposing `/voice/start`, `/voice/stop`, `/voice/stream` (SSE), `/voice/reload-model`
- `ml/intent_classifier.py` — TF-IDF + Logistic Regression intent model + expression normalizer
- `ml/data/voice_intent_dataset.json` — bootstrapped dataset (editable)
- `ml/data/voice_expression_pairs.json` — saved transcript↔expression pairs
- `manual_trainer.py` — microphone-based trainer UI

## Notes

- This backend buffers partial phrases and triggers equals immediately when you say "is equal to". Saying "clear" flushes both the UI and backend buffer.
- For hackathons, keep the backend running on the demo laptop and deploy the front-end publicly so judges can open it; the mic-powered backend processes your speech locally.

## Free + best performance (recommended)

Goal: zero hosting cost, minimum latency. Run the voice backend on your Windows laptop (uses the built‑in mic), expose it securely over the internet via a free Cloudflare Tunnel, and host the static frontend anywhere.

Windows steps (PowerShell):

```powershell
# 1) Create venv and install deps (run from project root containing requirements.txt)
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) Train/refresh the model (optional but recommended)
python -c "from ml.intent_classifier import IntentClassifier; IntentClassifier().retrain()"

# 3) Start the backend locally (keeps running)
uvicorn voice_service:app --host 127.0.0.1 --port 8000
```

Open a new PowerShell window for the tunnel:

```powershell
# 4) Install Cloudflare Tunnel (cloudflared)
winget install --id Cloudflare.cloudflared -e

# 5) Expose your local backend securely (no router changes needed)
cloudflared tunnel --url http://127.0.0.1:8000
```

The tunnel prints a few public URLs like https://random-string.trycloudflare.com. Copy one of them. In the frontend, set the API base without editing code:

1) Ensure `index.html` loads `config.js` (already wired above).
2) Create a file `config.js` next to `index.html` with:

```js
window.PROCALC_VOICE_API_BASE = "https://random-string.trycloudflare.com";
```

Reload the page, click the mic button, and speak. For best reliability, keep both the uvicorn server and cloudflared running during the demo.

Why this is best:
- Free: cloudflared is free; frontend can be on any free static host (GitHub Pages/Netlify/etc.).
- Low latency: speech processing stays on your laptop near the mic; only small events go over the tunnel.
- No mic on server required: avoids constraints of serverless or PaaS environments.
