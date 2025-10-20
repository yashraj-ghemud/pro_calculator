"""Interactive GUI for extending the voice intent training dataset.

Run this script to open a Tkinter interface that lets you append new
(transcript, label) samples, review existing data, and retrain the model that
powers the voice-enabled calculator experience.

Usage:
    python manual_trainer.py

Hotkeys:
    Ctrl+Return  -> Save sample
    Ctrl+Shift+R -> Retrain model immediately
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import List, Optional

import speech_recognition as sr
import tkinter as tk
from tkinter import messagebox, ttk

from ml.intent_classifier import (
    INTENT_LABELS,
    IntentClassifier,
    load_dataset,
    save_dataset,
    train_pipeline,
)

WINDOW_TITLE = "Pro Calculator Voice Trainer"
EXPRESSION_PAIRS_PATH = Path(__file__).resolve().parent / "ml" / "data" / "voice_expression_pairs.json"


def _sorted_labels() -> List[str]:
    return sorted(INTENT_LABELS)


class TrainerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry("720x520")
        self.root.minsize(640, 480)

        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.6
        self.intent_model = IntentClassifier()
        self.pending_sample: Optional[str] = None
        self.listening = False
        try:
            self.microphone = sr.Microphone()
            self.microphone_error: Optional[str] = None
        except Exception as exc:  # Microphone not available
            self.microphone = None
            self.microphone_error = str(exc)

        self.samples = load_dataset()
        self.expression_pairs = self._load_expression_pairs()

        self._build_layout()
        self._populate_table()
        self._bind_shortcuts()

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        layout = ttk.Frame(self.root, padding=12)
        layout.pack(fill=tk.BOTH, expand=True)

        form = ttk.LabelFrame(layout, text="Add training sample", padding=10)
        form.pack(fill=tk.X)

        self.text_var = tk.StringVar()
        ttk.Label(form, text="Recognised speech:").grid(row=0, column=0, sticky=tk.W)
        self.text_entry = ttk.Entry(form, textvariable=self.text_var, width=60)
        self.text_entry.grid(row=0, column=1, sticky=tk.EW, padx=6)
        self.text_entry.focus_set()

        ttk.Label(form, text="Intent label:").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self.label_var = tk.StringVar(value=_sorted_labels()[0])
        self.label_combo = ttk.Combobox(form, textvariable=self.label_var, values=_sorted_labels(), state="readonly")
        self.label_combo.grid(row=1, column=1, sticky=tk.W, padx=6, pady=(6, 0))

        ttk.Label(form, text="Expression (calculator):").grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
        self.expression_var = tk.StringVar()
        self.expression_entry = ttk.Entry(form, textvariable=self.expression_var, width=60, font=("Segoe UI", 16), justify=tk.RIGHT)
        self.expression_entry.grid(row=2, column=1, sticky=tk.EW, padx=6, pady=(6, 0))

        voice_frame = ttk.Frame(form)
        voice_frame.grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky=tk.EW)
        voice_frame.columnconfigure(0, weight=1)

        controls = ttk.Frame(voice_frame)
        controls.grid(row=0, column=0, sticky=tk.W)
        self.listen_button = ttk.Button(controls, text="🎙️ Start listening", command=self.start_listening)
        self.listen_button.pack(side=tk.LEFT)
        self.accept_button = ttk.Button(controls, text="✓ Tick", command=self.accept_voice_sample, state=tk.DISABLED)
        self.accept_button.pack(side=tk.LEFT, padx=(6, 0))
        self.correct_button = ttk.Button(controls, text="✏️ Make change", command=self.enable_correction, state=tk.DISABLED)
        self.correct_button.pack(side=tk.LEFT, padx=(6, 0))

        self.voice_status_var = tk.StringVar(value="Mic idle")
        ttk.Label(voice_frame, textvariable=self.voice_status_var).grid(row=0, column=1, sticky=tk.E)

        if self.microphone is None:
            self.voice_status_var.set(f"Mic unavailable: {self.microphone_error}")
            self.listen_button.config(state=tk.DISABLED)

        button_frame = ttk.Frame(form)
        button_frame.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky=tk.E)

        self.add_button = ttk.Button(button_frame, text="Save sample", command=self.add_sample)
        self.add_button.pack(side=tk.LEFT, padx=(0, 6))
        self.clear_button = ttk.Button(button_frame, text="Clear fields", command=self._clear_form)
        self.clear_button.pack(side=tk.LEFT)

        form.columnconfigure(1, weight=1)

        table_frame = ttk.LabelFrame(layout, text="Current dataset", padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        columns = ("text", "label")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("text", text="Transcript")
        self.tree.heading("label", text="Label")
        self.tree.column("text", width=420)
        self.tree.column("label", width=120)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        actions = ttk.Frame(layout)
        actions.pack(fill=tk.X, pady=(10, 0))

        self.delete_button = ttk.Button(actions, text="Delete selected", command=self.delete_selected)
        self.delete_button.pack(side=tk.LEFT)

        self.retrain_button = ttk.Button(actions, text="Retrain model", command=self.retrain_model)
        self.retrain_button.pack(side=tk.RIGHT)

        self.status_var = tk.StringVar(value="Dataset loaded")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(8, 4))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-Return>", lambda _: self.add_sample())
        self.root.bind("<Control-Shift-R>", lambda _: self.retrain_model())

    # ------------------------------------------------------------------
    def _load_expression_pairs(self) -> List[dict]:
        EXPRESSION_PAIRS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not EXPRESSION_PAIRS_PATH.exists():
            EXPRESSION_PAIRS_PATH.write_text("[]", encoding="utf-8")
        with EXPRESSION_PAIRS_PATH.open("r", encoding="utf-8") as handle:
            try:
                return json.load(handle)
            except json.JSONDecodeError:
                return []

    def _append_expression_pair(self, transcript: str, expression: str) -> None:
        if not expression:
            return
        record = {"transcript": transcript, "expression": expression}
        self.expression_pairs.append(record)
        EXPRESSION_PAIRS_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPRESSION_PAIRS_PATH.write_text(json.dumps(self.expression_pairs, indent=2), encoding="utf-8")

    def _set_text_entry_state(self, readonly: bool) -> None:
        state = "readonly" if readonly else tk.NORMAL
        self.text_entry.configure(state=state)

    # ------------------------------------------------------------------
    def _populate_table(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        for idx, sample in enumerate(self.samples):
            self.tree.insert("", tk.END, iid=str(idx), values=(sample["text"], sample["label"]))

    def _clear_form(self) -> None:
        self.text_var.set("")
        self.label_var.set(_sorted_labels()[0])
        self.text_entry.focus_set()
        self.pending_sample = None
        self.accept_button.config(state=tk.DISABLED)
        self.correct_button.config(state=tk.DISABLED)
        if not self.listening and self.microphone is not None:
            self.voice_status_var.set("Mic idle")
        self.expression_var.set("")
        self._set_text_entry_state(False)

    def add_sample(self) -> None:
        text = self.text_var.get().strip()
        label = self.label_var.get().strip()

        if not text:
            messagebox.showwarning("Missing text", "Please provide the transcribed text for the sample.")
            return
        if label not in INTENT_LABELS:
            messagebox.showerror("Invalid label", f"Choose one of: {', '.join(INTENT_LABELS)}")
            return

        self.samples.append({"text": text, "label": label})
        save_dataset(self.samples)
        self._populate_table()
        self._clear_form()
        self.status_var.set(f"Added sample for label '{label}'.")

    def accept_voice_sample(self) -> None:
        if not self.pending_sample:
            self.status_var.set("No voice sample to save.")
            return
        expression = self.expression_var.get().strip()
        if not expression:
            self.status_var.set("Expression empty. Adjust before ticking.")
            self.expression_entry.focus_set()
            return
        transcript = self.text_var.get().strip()
        self._save_voice_training_sample(transcript, expression)
        self.status_var.set("Saved analysed expression from voice input.")
        self._clear_form()

    def enable_correction(self) -> None:
        if not self.pending_sample:
            self.status_var.set("Use the mic first before making changes.")
            return
        self.expression_entry.focus_set()
        self.expression_entry.selection_range(0, tk.END)
        self.status_var.set("Adjust the expression, then tick to confirm.")

    def delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select a row to delete from the dataset.")
            return

        idx = int(selection[0])
        sample = self.samples.pop(idx)
        save_dataset(self.samples)
        self._populate_table()
        self.status_var.set(f"Removed sample '{sample['text'][:32]}…'.")

    def retrain_model(self) -> None:
        try:
            train_pipeline(self.samples, persist=True)
        except Exception as exc:
            messagebox.showerror("Training failed", f"Unable to train model: {exc}")
            return
        self.status_var.set("Model retrained and saved.")

    # ------------------------------------------------------------------
    def start_listening(self) -> None:
        if self.listening or self.microphone is None:
            return
        self.listening = True
        self.voice_status_var.set("Calibrating microphone…")
        self.listen_button.config(state=tk.DISABLED)
        threading.Thread(target=self._capture_voice_worker, daemon=True).start()

    def _capture_voice_worker(self) -> None:
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                self.root.after(0, lambda: self.voice_status_var.set("Listening…"))
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=7)
        except sr.WaitTimeoutError:
            self.root.after(0, lambda: self._on_voice_error("No speech detected."))
            return
        except Exception as exc:
            self.root.after(0, lambda: self._on_voice_error(f"Mic error: {exc}"))
            return

        try:
            transcript = self.recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            self.root.after(0, lambda: self._on_voice_error("Could not understand, try again."))
            return
        except sr.RequestError as exc:
            self.root.after(0, lambda: self._on_voice_error(f"Speech service error: {exc}"))
            return

        result = self.intent_model.interpret(transcript)
        label = result.intent if result.intent in INTENT_LABELS else "expression"
        confidence = result.confidence
        display_text = transcript.strip()
        expression = result.expression or display_text

        self.root.after(0, lambda: self._on_voice_result(display_text, label, confidence, expression))

    def _on_voice_result(self, transcript: str, label: str, confidence: float, expression: Optional[str]) -> None:
        self.listening = False
        self.listen_button.config(state=tk.NORMAL)
        self.accept_button.config(state=tk.NORMAL)
        self.correct_button.config(state=tk.NORMAL)
        self.pending_sample = transcript

        self.text_var.set(transcript)
        if label in INTENT_LABELS:
            self.label_var.set(label)

        if expression:
            self.expression_var.set(expression)
        else:
            self.expression_var.set(transcript)

        self._set_text_entry_state(True)

        hint = expression if expression and expression != transcript else transcript
        self.voice_status_var.set(f"Heard ({confidence:.2f}): {hint}")
        self.status_var.set("Review the analysed expression. Tick to keep or edit it before saving.")

    def _on_voice_error(self, message: str) -> None:
        self.listening = False
        self.listen_button.config(state=tk.NORMAL if self.microphone else tk.DISABLED)
        self.accept_button.config(state=tk.DISABLED)
        self.correct_button.config(state=tk.DISABLED)
        self.pending_sample = None
        self.voice_status_var.set(message)
        self.status_var.set(message)
        self._set_text_entry_state(False)

    def _save_voice_training_sample(self, transcript: str, expression: str) -> None:
        entries = []
        if transcript:
            entries.append({"text": transcript, "label": "expression"})
        if expression:
            entries.append({"text": expression, "label": "expression"})
        if not entries:
            return
        self.samples.extend(entries)
        save_dataset(self.samples)
        self._append_expression_pair(transcript, expression)
        self._populate_table()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    TrainerApp().run()
