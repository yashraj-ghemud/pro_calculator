"""Intent detection and expression normalization for voice-controlled calculator.

This module bundles a lightweight scikit-learn pipeline that classifies
recognized speech into high-level intents (expression, calculate, clear, etc.)
while also providing deterministic normalization utilities to convert free-form
speech into calculator-friendly math expressions.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_FILE = DATA_DIR / "voice_intent_dataset.json"
MODEL_FILE = DATA_DIR / "intent_model.joblib"

# Public list of supported intents; used by both the voice service and trainer UI.
INTENT_LABELS: Tuple[str, ...] = (
    "expression",
    "calculate",
    "clear",
    "backspace",
    "stop",
    "noop",
)

# Default training corpus used to bootstrap the intent classifier the first time.
DEFAULT_DATASET: List[Dict[str, str]] = [
    {"text": "equals", "label": "calculate"},
    {"text": "calculate", "label": "calculate"},
    {"text": "show result", "label": "calculate"},
    {"text": "what is the answer", "label": "calculate"},
    {"text": "finish the calculation", "label": "calculate"},
    {"text": "clear", "label": "clear"},
    {"text": "clear everything", "label": "clear"},
    {"text": "reset calculator", "label": "clear"},
    {"text": "wipe it", "label": "clear"},
    {"text": "backspace", "label": "backspace"},
    {"text": "delete last", "label": "backspace"},
    {"text": "remove the last digit", "label": "backspace"},
    {"text": "undo", "label": "backspace"},
    {"text": "stop listening", "label": "stop"},
    {"text": "mic off", "label": "stop"},
    {"text": "end voice control", "label": "stop"},
    {"text": "don't listen", "label": "stop"},
    {"text": "ignore this", "label": "noop"},
    {"text": "never mind", "label": "noop"},
    {"text": "random words", "label": "noop"},
    {"text": "one plus two", "label": "expression"},
    {"text": "seven times five", "label": "expression"},
    {"text": "twelve minus four", "label": "expression"},
    {"text": "thirty three divided by eleven", "label": "expression"},
    {"text": "open bracket three plus four close bracket", "label": "expression"},
    {"text": "nine point five plus two", "label": "expression"},
    {"text": "add six and eight", "label": "expression"},
    {"text": "subtract seven from nineteen", "label": "expression"},
    {"text": "multiply four by three", "label": "expression"},
    {"text": "divide twenty by five", "label": "expression"},
    {"text": "forty six plus seven whole multiply by four", "label": "expression"},
    {"text": "open bracket twelve minus five close bracket times nine", "label": "expression"},
    {"text": "sum of eight and four whole divide by two", "label": "expression"},
    {"text": "add five and nine then multiply by two", "label": "expression"},
    {"text": "modulus of nineteen and four", "label": "expression"},
    {"text": "twenty three mod five", "label": "expression"},
    {"text": "thirty six modulo eight", "label": "expression"},
    {"text": "remainder when fifty three is divided by six", "label": "expression"},
    {"text": "open parenthesis forty plus ten close parenthesis times three", "label": "expression"},
    {"text": "seventy two divided by open bracket eight minus two close bracket", "label": "expression"},
]

SMALL_NUMBER_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]

TENS_WORDS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}


def number_to_words(value: int) -> str:
    if value < 0:
        return "minus " + number_to_words(-value)
    if value < len(SMALL_NUMBER_WORDS):
        return SMALL_NUMBER_WORDS[value]
    if value < 100:
        tens = (value // 10) * 10
        remainder = value % 10
        base = TENS_WORDS.get(tens, str(value))
        return base if remainder == 0 else f"{base} {SMALL_NUMBER_WORDS[remainder]}"
    if value < 1000:
        hundreds = value // 100
        remainder = value % 100
        base = f"{SMALL_NUMBER_WORDS[hundreds]} hundred"
        return base if remainder == 0 else f"{base} {number_to_words(remainder)}"
    return str(value)


def synthetic_expression_corpus() -> List[Dict[str, str]]:
    numbers = [
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        14,
        15,
        16,
        18,
        19,
        20,
        22,
        24,
        25,
        27,
        30,
        32,
        36,
        40,
        42,
        45,
        48,
        50,
        54,
        60,
        64,
        72,
        84,
        96,
    ]

    modulus_numbers = [19, 23, 36, 53, 64, 75]
    triple_numbers = numbers[:10]
    phrases: Dict[str, Dict[str, str]] = {}

    def add_phrase(text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        key = cleaned.lower()
        if key not in phrases:
            phrases[key] = {"text": cleaned, "label": "expression"}

    for a in numbers:
        for b in numbers:
            words_a = number_to_words(a)
            words_b = number_to_words(b)
            add_phrase(f"{words_a} plus {words_b}")
            add_phrase(f"add {words_a} to {words_b}")
            add_phrase(f"sum of {words_a} and {words_b}")
            add_phrase(f"{words_a} minus {words_b}")
            add_phrase(f"subtract {words_b} from {words_a}")
            add_phrase(f"take away {words_b} from {words_a}")
            add_phrase(f"{words_a} times {words_b}")
            add_phrase(f"{words_a} multiply by {words_b}")
            add_phrase(f"product of {words_a} and {words_b}")
            add_phrase(f"{words_a} divided by {words_b}")
            add_phrase(f"divide {words_a} by {words_b}")
            add_phrase(f"{words_a} over {words_b}")
            add_phrase(f"{words_a} mod {words_b}")
            add_phrase(f"modulus of {words_a} and {words_b}")
            add_phrase(f"{a} + {b}")
            add_phrase(f"{a} - {b}")
            add_phrase(f"{a} * {b}")
            add_phrase(f"{a} / {b}")

    for a in modulus_numbers:
        for b in range(2, 12):
            words_a = number_to_words(a)
            words_b = number_to_words(b)
            add_phrase(f"remainder when {words_a} is divided by {words_b}")
            add_phrase(f"what's the remainder if {words_a} is divided by {words_b}")
            add_phrase(f"{a} % {b}")

    for a in triple_numbers:
        for b in triple_numbers:
            for c in triple_numbers:
                words_a = number_to_words(a)
                words_b = number_to_words(b)
                words_c = number_to_words(c)
                add_phrase(f"{words_a} plus {words_b} minus {words_c}")
                add_phrase(f"{words_a} plus {words_b} times {words_c}")
                add_phrase(f"{words_a} minus {words_b} divided by {words_c}")
                add_phrase(f"open bracket {words_a} plus {words_b} close bracket times {words_c}")
                add_phrase(f"open bracket {words_a} minus {words_b} close bracket divided by {words_c}")
                add_phrase(f"{a} + {b} - {c}")
                add_phrase(f"({a} + {b}) * {c}")
                add_phrase(f"({a} - {b}) / {c}")
                add_phrase(f"{words_a} plus {words_b} whole divide by {words_c}")
                add_phrase(f"{words_a} plus {words_b} whole multiply by {words_c}")

    for a in numbers[:12]:
        for b in numbers[:12]:
            for c in numbers[:12]:
                words_a = number_to_words(a)
                words_b = number_to_words(b)
                words_c = number_to_words(c)
                add_phrase(f"open parenthesis {words_a} plus {words_b} close parenthesis times {words_c}")
                add_phrase(f"{words_a} plus open bracket {words_b} times {words_c} close bracket")

    return list(phrases.values())


def _ensure_dataset() -> List[Dict[str, str]]:
    """Guarantee that a dataset file exists and return its parsed content."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps(DEFAULT_DATASET, indent=2), encoding="utf-8")
    with DATA_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_dataset() -> List[Dict[str, str]]:
    """Load the dataset from disk (ensuring defaults if missing)."""
    return _ensure_dataset()


def save_dataset(records: Iterable[Dict[str, str]]) -> None:
    """Persist the dataset back to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    serialisable = list(records)
    DATA_FILE.write_text(json.dumps(serialisable, indent=2), encoding="utf-8")


def train_pipeline(records: Iterable[Dict[str, str]], persist: bool = True) -> Pipeline:
    """Train an intent classification pipeline and optionally persist it."""
    records_list = list(records)
    synthetic_records = synthetic_expression_corpus()

    merged: Dict[str, Dict[str, str]] = {}
    for entry in list(records_list) + synthetic_records:
        text = entry["text"].strip()
        if not text:
            continue
        key = text.lower()
        if key not in merged:
            merged[key] = {"text": text, "label": entry["label"]}

    records_list = list(merged.values())
    if not records_list:
        raise ValueError("Cannot train intent classifier without samples")

    texts = [row["text"] for row in records_list]
    labels = [row["label"] for row in records_list]

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
        ("clf", LogisticRegression(max_iter=400, multi_class="auto")),
    ])
    pipeline.fit(texts, labels)

    if persist:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, MODEL_FILE)

    return pipeline


def _load_pipeline() -> Pipeline:
    """Load a persisted pipeline or fall back to training one."""
    dataset = _ensure_dataset()
    if MODEL_FILE.exists():
        try:
            return joblib.load(MODEL_FILE)
        except Exception:
            # Fall back to retraining if the cached model is incompatible.
            pass
    return train_pipeline(dataset, persist=True)


# === Normalisation helpers ===================================================
NUMBER_WORDS: Dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
}

OPERATOR_WORDS: Dict[str, str] = {
    "plus": "+",
    "add": "+",
    "sum": "+",
    "+": "+",
    "minus": "-",
    "subtract": "-",
    "negative": "-",
    "-": "-",
    "times": "*",
    "x": "*",
    "into": "*",
    "multiply": "*",
    "multiplied": "*",
    "*": "*",
    "divide": "/",
    "divided": "/",
    "over": "/",
    "slash": "/",
    "/": "/",
    "percent": "%",
    "%": "%",
    "mod": "%",
    "modulo": "%",
    "modulus": "%",
    "remainder": "%",
}

SPECIAL_TOKENS: Dict[str, str] = {
    "point": ".",
    "dot": ".",
    "decimal": ".",
    "comma": ".",
    "open": "(",
    "left": "(",
    "opening": "(",
    "close": ")",
    "closing": ")",
    "right": ")",
    "bracket": "()",  # Placeholder handled specially
    "parenthesis": "()",
    "equals": "=",
    "equal": "=",
    "is": "=",
}

BRACKET_WORDS = {"bracket", "parenthesis", "parentheses"}
FILLER_WORDS = {
    "by",
    "of",
    "the",
    "a",
    "an",
    "and",
    "then",
    "from",
    "to",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "being",
    "been",
    "into",
    "per",
}


def _collapse_number_sequence(words: List[str]) -> Optional[int]:
    """Convert a consecutive sequence of number words into an integer."""
    if not words:
        return None

    total = 0
    current = 0
    for word in words:
        value = NUMBER_WORDS.get(word)
        if value is None:
            return None
        if value == 100:
            if current == 0:
                current = 1
            current *= 100
        else:
            current += value
    total += current
    return total


def _tokenise_transcript(transcript: str) -> List[str]:
    cleaned = transcript.lower().strip()
    # Normalise common multi-word phrases before tokenisation.
    phrase_map = {
        "divided by": "divide",
        "multiplied by": "multiply",
        "times by": "multiply",
        "multiply by": "multiply",
        "multiply with": "multiply",
        "multiplied with": "multiply",
        "divide by": "divide",
        "divided into": "divide",
        "whole multiplied by": "whole multiply",
        "whole multiply by": "whole multiply",
        "whole divided by": "whole divide",
        "to the power of": "power",
        "raised to": "power",
        "open bracket": "open bracket",
        "open parenthesis": "open parenthesis",
        "left bracket": "open bracket",
        "left parenthesis": "open parenthesis",
        "close bracket": "close bracket",
        "close parenthesis": "close parenthesis",
        "right bracket": "close bracket",
        "right parenthesis": "close parenthesis",
    }
    for phrase, replacement in phrase_map.items():
        cleaned = cleaned.replace(phrase, replacement)

    cleaned = re.sub(r"remainder when ([a-z0-9 ]+?) is divided by ([a-z0-9 ]+)", r"\1 mod \2", cleaned)
    cleaned = re.sub(r"what's the remainder if ([a-z0-9 ]+?) is divided by ([a-z0-9 ]+)", r"\1 mod \2", cleaned)
    cleaned = re.sub(r"subtract ([a-z0-9 ]+?) from ([a-z0-9 ]+)", r"\2 minus \1", cleaned)
    cleaned = re.sub(r"take away ([a-z0-9 ]+?) from ([a-z0-9 ]+)", r"\2 minus \1", cleaned)
    cleaned = re.sub(r"add ([a-z0-9 ]+?) to ([a-z0-9 ]+)", r"\2 plus \1", cleaned)
    cleaned = re.sub(r"sum of ([a-z0-9 ]+?) and ([a-z0-9 ]+)", r"\1 plus \2", cleaned)
    cleaned = re.sub(r"difference between ([a-z0-9 ]+?) and ([a-z0-9 ]+)", r"\1 minus \2", cleaned)

    tokens = re.findall(r"[a-zA-Z]+|\d+|[+\-*/()=%]", cleaned)
    return tokens


def normalise_expression(transcript: str) -> Tuple[Optional[str], float]:
    """Convert free-form spoken math into a calculator-friendly expression."""
    tokens = _tokenise_transcript(transcript)
    if not tokens:
        return None, 0.0

    builder: List[str] = []
    buffer: List[str] = []
    matches = 0
    wrap_before_next_operator = False
    pending_operator: Optional[str] = None

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token in FILLER_WORDS:
            matches += 1
            buffer.clear()
            i += 1
            continue

        if token in {"whole", "entire", "all"}:
            wrap_before_next_operator = True
            matches += 1
            buffer.clear()
            i += 1
            continue

        if token in OPERATOR_WORDS:
            operator_symbol = OPERATOR_WORDS[token]
            if not builder or builder[-1] in OPERATOR_WORDS.values():
                pending_operator = operator_symbol
                matches += 1
                buffer.clear()
                i += 1
                continue

            if wrap_before_next_operator and builder:
                if builder[0] != "(":
                    builder.insert(0, "(")
                if builder[-1] != ")":
                    builder.append(")")
                wrap_before_next_operator = False
            builder.append(operator_symbol)
            matches += 1
            buffer.clear()
        elif token in {"(", ")"}:
            builder.append(token)
            matches += 1
            buffer.clear()
        elif token in BRACKET_WORDS:
            prev = tokens[i - 1] if i > 0 else ""
            if prev in {"open", "opening", "left"}:
                # The preceding token already inserted an opening bracket, so skip.
                matches += 1
            elif prev in {"close", "closing", "right"}:
                builder.append(")")
                matches += 1
            else:
                builder.append("(")
                matches += 1
            buffer.clear()
        elif token in SPECIAL_TOKENS:
            mapped = SPECIAL_TOKENS[token]
            if mapped == "()":
                prev = tokens[i - 1] if i > 0 else ""
                mapped = ")" if prev in {"close", "closing", "right"} else "("
            builder.append(mapped)
            matches += 1
            buffer.clear()
        elif token.isdigit():
            builder.append(token)
            matches += 1
            buffer.clear()
            if pending_operator:
                builder.append(pending_operator)
                pending_operator = None
        else:
            buffer.append(token)
            next_token = tokens[i + 1] if i + 1 < len(tokens) else None
            sequence = buffer[:]
            if next_token is None or next_token in OPERATOR_WORDS or next_token in SPECIAL_TOKENS or next_token.isdigit():
                number_value = _collapse_number_sequence(sequence)
                if number_value is not None:
                    builder.append(str(number_value))
                    matches += len(sequence)
                    buffer.clear()
                    if pending_operator:
                        builder.append(pending_operator)
                        pending_operator = None
                else:
                    buffer.clear()
        i += 1

    expression = ''.join(builder)
    expression = re.sub(r"[^0-9+\-*/().=]", "", expression)
    expression = expression.replace("=", "")
    expression = re.sub(r"([+\-*/]){2,}", r"\\1", expression)
    expression = re.sub(r"\.{2,}", ".", expression)
    expression = expression.rstrip("+-*/%")

    confidence = matches / len(tokens)
    if not expression:
        return None, confidence

    return expression, min(1.0, confidence)


@dataclass
class IntentResult:
    raw: str
    intent: str
    confidence: float
    action: str
    expression: Optional[str]
    expression_confidence: float


class IntentClassifier:
    """Bundle classifier + normalisation used by the voice service."""

    def __init__(self) -> None:
        self.dataset = _ensure_dataset()
        self.pipeline = _load_pipeline()

    def predict_intent(self, transcript: str) -> Tuple[str, float]:
        cleaned = transcript.strip()
        if not cleaned:
            return "noop", 0.0

        if hasattr(self.pipeline, "predict_proba"):
            probabilities = self.pipeline.predict_proba([cleaned])[0]
            idx = int(probabilities.argmax())
            label = self.pipeline.classes_[idx]
            return label, float(probabilities[idx])

        label = self.pipeline.predict([cleaned])[0]
        return label, 1.0

    def interpret(self, transcript: str) -> IntentResult:
        label, confidence = self.predict_intent(transcript)
        expression, expression_confidence = normalise_expression(transcript)

        lowered = transcript.lower()
        if any(trigger in lowered for trigger in ("equals", "equal", "result", "calculate")):
            label = "calculate"
            confidence = max(confidence, 0.6)

        action = "noop"
        if label == "calculate":
            action = "calculate"
        elif label == "clear":
            action = "clear"
        elif label == "backspace":
            action = "backspace"
        elif label == "stop":
            action = "stop"
        elif label == "expression" and expression:
            action = "append_expression"
        elif label == "noop" and expression:
            # Treat low-confidence expression as appendable to keep UX smooth.
            action = "append_expression"
            label = "expression"

        return IntentResult(
            raw=transcript,
            intent=label,
            confidence=confidence,
            action=action,
            expression=expression,
            expression_confidence=expression_confidence,
        )

    def append_training_sample(self, text: str, label: str) -> None:
        if label not in INTENT_LABELS:
            raise ValueError(f"Unsupported label: {label}")
        sample = {"text": text, "label": label}
        self.dataset.append(sample)
        save_dataset(self.dataset)

    def retrain(self) -> None:
        self.pipeline = train_pipeline(self.dataset, persist=True)


async def stream_intent_results(queue: "asyncio.Queue[IntentResult]"):
    """Helper used by the voice service to serialise intent outputs as dicts."""
    while True:
        result = await queue.get()
        payload = {
            "type": "result",
            "raw": result.raw,
            "intent": result.intent,
            "confidence": result.confidence,
            "action": result.action,
            "expression": result.expression,
            "expression_confidence": result.expression_confidence,
        }
        yield payload
