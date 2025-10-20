# Run voice service locally on Windows PowerShell
param(
    [string]$HostIP = "127.0.0.1",
    [int]$Port = 8000
)

if (-not (Test-Path .venv)) {
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -c "from ml.intent_classifier import IntentClassifier; IntentClassifier().retrain()"
uvicorn voice_service:app --host $HostIP --port $Port
