# pro_calculator
> A local-first web calculator with an optional voice-control layer — static frontend + FastAPI voice backend + lightweight intent classifier and a small trainer UI.

## Overview
Pro Calculator adds a voice-control layer to a static calculator UI. The repo contains a static frontend (HTML/CSS/JS + service worker), a local FastAPI voice service that transcribes audio and classifies voice intents, a small scikit-learn intent pipeline, and a Tkinter manual trainer for collecting samples and hot-retraining the model.

## What it does
- The frontend shows a calculator UI with a microphone toggle that talks to a local voice backend.
- The backend (voice_service.py) transcribes audio (SpeechRecognition by default), classifies intents (TF-IDF + LogisticRegression), normalizes spoken phrases into calculator expressions, and streams intent events to the UI via Server-Sent Events (SSE).
- A manual trainer (manual_trainer.py) captures transcripts and expression corrections; retraining persists model/data under ml/data/ and can be hot-reloaded into the running service.

## Key capabilities
- Voice-driven intents: expression, calculate, clear, backspace, stop, noop.
- SSE streaming of structured intent events to the frontend (/voice/stream).
- Control endpoints: /voice/start, /voice/stop, /voice/reload-model (documented in README).
- Local-first demo flow: frontend can be hosted publicly while voice backend runs on a demo machine (Cloudflare Tunnel guidance included in the project README).
- Trainer UI for manual sample collection and retrain workflow.
- Static frontend supports a service worker for simple offline caching.

## Technology
- Frontend: HTML, CSS, JavaScript, Service Worker (sw.js)
- Backend: FastAPI + uvicorn (voice_service.py)
- Speech: SpeechRecognition (default uses Google Web Speech) and PyAudio for microphone capture
- ML: scikit-learn (TfidfVectorizer + LogisticRegression), joblib for model persistence
- Trainer UI: Tkinter (manual_trainer.py)
- Python 3.11+ is recommended (per project README)
- Dependencies listed in requirements.txt

## Repository structure
Relevant top-level files and directories (high level):
- index.html, script.js, styles.css, sw.js — static frontend assets
- config.js — optional frontend override (not required)
- voice_service.py — FastAPI voice backend
- manual_trainer.py — Tkinter trainer UI
- ml/ — intent pipeline, data, model code (ml/intent_classifier.py and ml/data/)
- scripts/ — helper scripts (e.g., retrain, run helpers)
- requirements.txt — Python dependency pins
- deploy/ — referenced in README (systemd/nginx samples referenced) — note: some deploy artifacts referenced in the README are not present in the repository snapshot

## Getting started
The repository README includes a local demo quickstart. Example steps from the project README:

1. Create a virtual environment and install dependencies:
   - Powershell example
     ```
     python -m venv .venv
     . .venv/Scripts/Activate.ps1
     pip install -r requirements.txt
     ```
2. Train or refresh the intent model:
   ```
   python -c "from ml.intent_classifier import IntentClassifier; IntentClassifier().retrain()"
   ```
3. Run the voice service:
   ```
   uvicorn voice_service:app --host 127.0.0.1 --port 8000
   ```
4. Serve/open the frontend (any static server will work). Default voice API base is http://127.0.0.1:8000 (script.js), or override via config.js (see Configuration).

Manual trainer:
```
python manual_trainer.py
```
Hot-reload model into a running service:
- Example (PowerShell in README):
```
Invoke-WebRequest -Method POST http://127.0.0.1:8000/voice/reload-model
```

Note: the README recommends running the backend on a demo laptop and provides steps for exposing the local backend with Cloudflare Tunnel; those steps and the config.js pattern are present in the project README.

## Configuration
- VOICE_API_BASE: frontend uses a base URL for the voice API. Default is http://127.0.0.1:8000 (script.js).
- Override options:
  - Create config.js next to index.html containing:
    ```js
    window.PROCALC_VOICE_API_BASE = "https://your-domain"
    ```
    and load it before script.js.
  - The frontend code also supports URL param/localStorage overrides (script.js/config.js behavior described in README).
- Model and data are persisted under ml/data/ (voice_intent_dataset.json, voice_expression_pairs.json, joblib model files).
- requirements.txt (pinned deps) is present:
  - fastapi==0.115.0
  - uvicorn[standard]==0.30.6
  - SpeechRecognition==3.10.4
  - PyAudio==0.2.14
  - scikit-learn==1.5.2
  - joblib==1.4.2

## Development and quality notes
- No automated tests or CI configuration were found in the snapshot (no tests/ directory, no CI files).
- Model training is currently fire-and-forget; there is no train/validation split or persisted evaluation metrics in ml/intent_classifier.py or retrain scripts.
- The README references deploy/systemd and deploy/nginx.conf.sample, but those deploy artifacts were not present in the repository snapshot.
- Repository hygiene issue: styles.css contains unresolved Git conflict markers (<<<<<<<, >>>>>>>) and should be fixed before use.
- The backend exposes control endpoints (start/stop/reload) and CORS configuration is not shown — consider restricting CORS and protecting control endpoints before exposing the service publicly.
- The frontend evaluation path uses dynamic code evaluation for calculator expressions; exercise caution and review sanitization before running with untrusted inputs.

## Safety and responsible use
- Privacy: SpeechRecognition defaults to Google Web Speech in the current code/comments — audio may be sent to a third-party service unless an offline recognizer (e.g., Vosk) is configured. The project README calls this out; if privacy is a concern, do not use the default remote recognizer.
- Unprotected control endpoints: /voice/reload-model, /voice/start, /voice/stop appear unprotected in the documented service. Do not expose the backend publicly without adding access controls (API key, binding to localhost, or equivalent).
- CORS and network exposure: ensure CORS is restricted to known frontend origins before public exposure. The project is intended for local demos; take care if using tunnels (Cloudflare) or public hosting.
- Code execution risk: the frontend evaluates normalized expressions using a generated function. Although sanitization exists, executing dynamically generated code carries risk. Review and harden the evaluation path before use with untrusted inputs.
- Repository hygiene: fix merge conflict markers in styles.css before building or deploying.

## Contributing
- There is no explicit CONTRIBUTING.md in the repository snapshot.
- To contribute:
  - Inspect implementation and configuration in these files/directories: voice_service.py, ml/intent_classifier.py, ml/data/, manual_trainer.py, script.js, config.js, scripts/.
  - Open issues or pull requests in the repository to propose fixes or improvements (e.g., remove merge markers in styles.css, add tests, add CI, harden endpoints).
  - For quick local inspection, run the service and trainer per the Getting started steps above and examine ml/data/ for persisted datasets and model artifacts.

(Do not assume any further contribution workflow beyond the files in the repository.)
