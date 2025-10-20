"""Local FastAPI service that powers microphone-driven calculator control.

Run this module to expose an HTTP API that the calculator frontend can use to
start/stop streaming recognition results as well as receive live intent updates
via Server-Sent Events (SSE).

Usage:
    python voice_service.py

Dependencies:
    pip install fastapi uvicorn[standard] speechrecognition pyaudio scikit-learn joblib

Ensure you have a working microphone and (for the default recognizer) an active
internet connection. The recognizer leverages Google Web Speech. You can swap in
an offline engine like Vosk inside the `_transcribe_audio` method if desired.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import threading
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import speech_recognition as sr
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ml.intent_classifier import INTENT_LABELS, IntentClassifier
import os

DEFAULT_HOST = os.getenv("VOICE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("VOICE_PORT", "8000"))


class VoiceEngine:
    """Background recognizer that pushes structured voice intents into a queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.6
        try:
            self.microphone = sr.Microphone()
            self._mic_error: Optional[str] = None
        except Exception as exc:
            # Allow service to start without a microphone (headless deploy),
            # but voice/start will refuse and status will report error.
            self.microphone = None  # type: ignore[assignment]
            self._mic_error = str(exc)
        self.intent_model = IntentClassifier()
        self.queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._status = "idle"
        self._last_energy = 0.0
        self._expression_buffer: List[str] = []
        self._last_expression_time = 0.0

    # ---------------------------------------------------------------------
    @property
    def status(self) -> str:
        return self._status

    def _emit(self, payload: Dict[str, Any]) -> None:
        """Push payloads into the async queue from any thread safely."""
        asyncio.run_coroutine_threadsafe(self.queue.put(payload), self.loop)

    def _emit_status(self, message: str, level: str = "info", state: Optional[str] = None) -> None:
        payload = {
            "type": "status",
            "message": message,
            "level": level,
            "state": state or self._status,
            "timestamp": time.time(),
        }
        self._emit(payload)

    def start(self) -> None:
        if self._running.is_set():
            self._emit_status("Voice capture already running", state=self._status)
            return

        if self.microphone is None:
            self._status = "error"
            self._emit_status("Microphone unavailable on this host", level="error", state=self._status)
            return

        self._running.set()
        self._status = "calibrating"
        self._emit_status("Calibrating microphone…", state=self._status)

        self._thread = threading.Thread(target=self._run, name="VoiceEngine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running.is_set():
            self._status = "idle"
            self._emit_status("Voice capture idle", state=self._status)
            return

        self._running.clear()
        self._status = "stopping"
        self._emit_status("Stopping microphone stream…", state=self._status)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._status = "idle"
        self._emit_status("Voice capture stopped", state=self._status)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            with self.microphone as source:
                try:
                    self.recognizer.adjust_for_ambient_noise(source, duration=1.5)
                    self._status = "listening"
                    self._emit_status("Listening for commands…", state=self._status)
                except Exception as exc:  # Microphone or calibration failure
                    self._status = "error"
                    self._emit_status(f"Microphone calibration failed: {exc}", level="error", state=self._status)
                    self._running.clear()
                    return

                while self._running.is_set():
                    try:
                        audio = self.recognizer.listen(source, timeout=3, phrase_time_limit=7)
                    except sr.WaitTimeoutError:
                        continue
                    except Exception as exc:
                        self._emit_status(f"Microphone error: {exc}", level="error", state="error")
                        continue

                    if not self._running.is_set():
                        break

                    if not self._is_voice_confident(audio):
                        self._emit_status("Discarded low-energy audio", level="debug", state=self._status)
                        continue

                    transcript = self._transcribe_audio(audio)
                    if transcript is None:
                        continue

                    result = self.intent_model.interpret(transcript)
                    payloads = self._handle_intent_result(result)
                    for payload in payloads:
                        self._emit(payload)

                    if any(p["action"] == "stop" for p in payloads):
                        self.stop()
                        break
        finally:
            self._status = "idle"
            self._running.clear()

    def _transcribe_audio(self, audio: sr.AudioData) -> Optional[str]:
        try:
            transcript = self.recognizer.recognize_google(audio)
            return transcript.strip()
        except sr.UnknownValueError:
            self._emit_status("Could not understand audio", level="warning", state=self._status)
        except sr.RequestError as exc:
            self._status = "error"
            self._emit_status(f"Speech service error: {exc}", level="error", state=self._status)
            self.stop()
        return None

    def _is_voice_confident(self, audio: sr.AudioData) -> bool:
        """Simple energy gate to filter out background noise."""
        try:
            raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        except Exception:
            raw = audio.frame_data
        if not raw:
            return False

        samples = array.array("h", raw)
        if not samples:
            return False

        mean_square = sum(sample * sample for sample in samples) / len(samples)
        rms = math.sqrt(mean_square)
        self._last_energy = rms
        return rms > 150  # Empirically chosen threshold

    # ------------------------------------------------------------------
    def reload_model(self) -> None:
        self.intent_model.retrain()
        self._emit_status("Intent model reloaded", level="info", state=self._status)

    # ------------------------------------------------------------------
    def _handle_intent_result(self, result) -> List[Dict[str, Any]]:
        now = time.time()
        outputs: List[Dict[str, Any]] = []

        def emit(action: str, expression: Optional[str]) -> None:
            outputs.append({
                "type": "result",
                "raw": result.raw,
                "intent": result.intent,
                "confidence": result.confidence,
                "action": action,
                "expression": expression,
                "expression_confidence": result.expression_confidence,
                "timestamp": now,
            })

        if result.action == "append_expression" and result.expression:
            if now - self._last_expression_time > 1.5:
                self._expression_buffer.clear()
            self._expression_buffer.append(result.expression)
            self._last_expression_time = now
            combined = ' '.join(self._expression_buffer)
            emit("append_expression", combined)
        elif result.action == "calculate":
            combined = ' '.join(self._expression_buffer).strip()
            self._expression_buffer.clear()
            self._last_expression_time = 0.0
            payload_expression = combined or result.expression
            emit("calculate", payload_expression)
        else:
            if result.action in {"clear", "backspace", "stop"}:
                self._expression_buffer.clear()
                self._last_expression_time = 0.0
            payload_expression = None if result.action == "clear" else result.expression
            emit(result.action, payload_expression)

        return outputs


app = FastAPI(title="Pro Calculator Voice Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

voice_engine: Optional[VoiceEngine] = None
class InterpretRequest(BaseModel):
    transcript: str

class InterpretResponse(BaseModel):
    type: str = "result"
    raw: str
    intent: str
    confidence: float
    action: str
    expression: Optional[str]
    expression_confidence: float



@app.on_event("startup")
async def _startup() -> None:
    global voice_engine
    loop = asyncio.get_running_loop()
    voice_engine = VoiceEngine(loop)


@app.on_event("shutdown")
async def _shutdown() -> None:
    if voice_engine:
        voice_engine.stop()


@app.post("/voice/start")
async def start_voice() -> Dict[str, Any]:
    assert voice_engine is not None
    if voice_engine.microphone is None:
        # Surface a proper HTTP error for cloud/CI environments without audio devices
        raise HTTPException(status_code=503, detail={
            "status": "error",
            "reason": "microphone-unavailable",
            "message": "No microphone detected on server",
        })
    voice_engine.start()
    return {"status": voice_engine.status}


@app.post("/voice/stop")
async def stop_voice() -> Dict[str, Any]:
    assert voice_engine is not None
    voice_engine.stop()
    return {"status": voice_engine.status}


@app.post("/voice/reload-model")
async def reload_model() -> Dict[str, Any]:
    assert voice_engine is not None
    voice_engine.reload_model()
    return {"status": "model reloaded"}


@app.get("/voice/status")
async def voice_status() -> Dict[str, Any]:
    assert voice_engine is not None
    return {
        "status": voice_engine.status,
        "supported_intents": list(INTENT_LABELS),
        "micAvailable": voice_engine.microphone is not None,
        "micError": getattr(voice_engine, "_mic_error", None),
    }


@app.post("/voice/interpret", response_model=InterpretResponse)
async def voice_interpret(body: InterpretRequest) -> Dict[str, Any]:
    assert voice_engine is not None
    text = (body.transcript or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty transcript")
    result = voice_engine.intent_model.interpret(text)
    return {
        "type": "result",
        "raw": result.raw,
        "intent": result.intent,
        "confidence": result.confidence,
        "action": result.action,
        "expression": result.expression,
        "expression_confidence": result.expression_confidence,
    }


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True}


@app.get("/voice/stream")
async def voice_stream() -> StreamingResponse:
    assert voice_engine is not None

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                payload = await asyncio.wait_for(voice_engine.queue.get(), timeout=20)
                yield f"data: {json.dumps(payload)}\n\n"
            except asyncio.TimeoutError:
                yield "event: ping\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("voice_service:app", host=DEFAULT_HOST, port=DEFAULT_PORT, reload=False)
