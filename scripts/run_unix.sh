#!/usr/bin/env bash
set -euo pipefail
HOST_IP=${1:-127.0.0.1}
PORT=${2:-8000}

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "from ml.intent_classifier import IntentClassifier; IntentClassifier().retrain()"
uvicorn voice_service:app --host "$HOST_IP" --port "$PORT"
