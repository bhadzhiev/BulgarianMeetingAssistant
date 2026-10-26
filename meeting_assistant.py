#!/usr/bin/env python3
"""Local, near-real-time Bulgarian meeting transcription for Apple Silicon."""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import json
import os
import queue
import re
import signal
import sys
import time
import urllib.request
import wave
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.storage import atomic_text
from app.whisper import remove_hallucinations

import numpy as np
import sounddevice as sd
from pywhispercpp.model import Model

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 480  # 30 ms
FRAME_BYTES = FRAME_SAMPLES * 2


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None


def timestamp(seconds: float, srt: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    separator = "," if srt else "."
    if srt:
        return f"{hours:02}:{minutes:02}:{secs:02}{separator}{milliseconds:03}"
    return f"{hours:02}:{minutes:02}:{secs:02}"


def clean_text(text: str) -> str:
    text = re.sub(r"\[[^\]]*]|\([^)]*(?:silence|noise|music)[^)]*\)", "", text, flags=re.I)
    return remove_hallucinations(re.sub(r"\s+", " ", text).strip())


def find_device(selector: str | None) -> int:
    devices = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    if selector is None:
        iphone = [(i, d) for i, d in inputs if "iphone" in d["name"].lower()]
        if iphone:
            return iphone[0][0]
        return sd.default.device[0]
    if selector.isdigit():
        index = int(selector)
        if index not in {i for i, _ in inputs}:
            raise ValueError(f"Device {index} is not an input device")
        return index
    matches = [(i, d) for i, d in inputs if selector.lower() in d["name"].lower()]
    if len(matches) != 1:
        names = ", ".join(f"{i}: {d['name']}" for i, d in inputs)
        raise ValueError(f"Microphone selector must match exactly one device. Available: {names}")
    return matches[0][0]


def list_devices() -> None:
    for i, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0:
            print(f"{i}: {device['name']} ({int(device['default_samplerate'])} Hz)")


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(samples.astype(np.int16).tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != SAMPLE_RATE:
            raise ValueError("Expected 16 kHz, mono, 16-bit PCM WAV")
        return np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16).copy()


def save_transcript(output_dir: Path, segments: list[TranscriptSegment]) -> None:
    serializable = [asdict(segment) for segment in segments]
    atomic_text(output_dir / "transcript.json", 
        json.dumps(serializable, ensure_ascii=False, indent=2)
    )
    from app.transcripts import meeting_title, transcript_markdown
    atomic_text(output_dir / "transcript.md", transcript_markdown(segments, meeting_title(output_dir)))

    cues = []
    for index, segment in enumerate(segments, 1):
        cues.append(
            f"{index}\n{timestamp(segment.start, True)} --> {timestamp(segment.end, True)}\n"
            f"{(segment.speaker + ': ') if segment.speaker else ''}{segment.text}\n"
        )
    atomic_text(output_dir / "transcript.srt", "\n".join(cues))


def merge_segments(raw_segments: list[Any], offset: float = 0) -> list[TranscriptSegment]:
    merged: list[TranscriptSegment] = []
    for segment in raw_segments:
        text = clean_text(segment.text)
        if not text:
            continue
        start = offset + max(0, segment.t0 / 100)
        end = offset + max(0, segment.t1 / 100)
        if merged and text == merged[-1].text and start < merged[-1].end:
            continue
        if (merged and 0 <= start - merged[-1].end < 0.8
                and len(merged[-1].text) + len(text) < 180
                and end - merged[-1].start <= 10):
            merged[-1].text = f"{merged[-1].text} {text}"
            merged[-1].end = end
        else:
            merged.append(TranscriptSegment(start=start, end=end, text=text))
    return merged


class LiveMeeting:
    def __init__(self, args: argparse.Namespace, output_dir: Path):
        self.args = args
        self.output_dir = output_dir
        self.audio_queue: queue.Queue = queue.Queue(maxsize=200)
        self.segments: list[TranscriptSegment] = []
        self.stop_requested = False
        self.total_samples = 0
        self.buffer: list[np.ndarray] = []
        self.buffer_start = 0
        self.pre_roll: deque[tuple[int, np.ndarray]] = deque(maxlen=max(1, round(args.pre_roll / 0.03)))
        self.silence = 0.0
        self.last_partial = 0.0
        self.partial_text = ""
        self.model = Model(
            args.live_model,
            models_dir=str(Path(args.models_dir).resolve()),
            language="bg",
            translate=False,
            print_progress=False,
            print_realtime=False,
            print_timestamps=False,
            single_segment=True,
            no_context=True,
            suppress_blank=True,
            suppress_non_speech_tokens=True,
            temperature=0.0,
            n_threads=args.threads,
        )

    def audio_callback(self, data: bytes, frames: int, time_info: Any, status: Any) -> None:
        if status:
            print(f"Audio warning: {status}", file=sys.stderr)
        self.audio_queue.put(bytes(data))

    def transcribe(self, final: bool = False) -> None:
        if not self.buffer:
            return
        samples = np.concatenate(self.buffer)
        duration = len(samples) / SAMPLE_RATE
        if duration < self.args.min_speech:
            return
        now = time.monotonic()
        if not final and now - self.last_partial < self.args.partial_interval:
            return
        self.last_partial = now
        audio = samples.astype(np.float32) / 32768.0
        raw = self.model.transcribe(audio, language="bg", single_segment=True, no_context=True)
        text = clean_text(" ".join(segment.text for segment in raw))
        if not text:
            return
        start = self.buffer_start / SAMPLE_RATE
        if final:
            end = start + duration
            new_segments = merge_segments(raw, start)
            if not new_segments:
                new_segments = [TranscriptSegment(start, end, text)]
            self.segments.extend(new_segments)
            self.segments.sort(key=lambda item: item.start)
            save_transcript(self.output_dir, self.segments)
            print("\r" + " " * 100 + "\r", end="")
            print(f"[{timestamp(start)}] {text}", flush=True)
            self.partial_text = ""
        elif text != self.partial_text:
            self.partial_text = text
            print(f"\r\x1b[2K[{timestamp(start)}] … {text}", end="", flush=True)

    def finish_utterance(self) -> None:
        self.transcribe(final=True)
        self.buffer = []
        self.silence = 0.0
        self.last_partial = 0.0

    def resample_frame(self, frame_bytes: bytes) -> np.ndarray:
        frame = np.frombuffer(frame_bytes, dtype=np.int16).copy()
        if self.capture_rate == SAMPLE_RATE:
            return frame
        output_length = round(len(frame) * SAMPLE_RATE / self.capture_rate)
        source_positions = np.arange(len(frame))
        target_positions = np.linspace(0, len(frame) - 1, output_length)
        return np.interp(target_positions, source_positions, frame).round().astype(np.int16)

    def run(self, device: int) -> None:
        from app.capture import Recorder, render_recording
        recorder = Recorder(self.output_dir, device, "in_person", Path("bin/SystemAudio"))
        self.capture_rate = recorder.rate
        dropped = [False]

        def live_frame(data: bytes, position: int):
            try:
                self.audio_queue.put_nowait((position, data))
            except queue.Full:
                # Captions may skip ahead; the independent disk writer retains the audio.
                dropped[0] = True

        recorder.on_frame = live_frame
        print(f"Live model: {self.args.live_model}; language: Bulgarian")
        print("Recording… Press Ctrl+C to stop. Audio is saved continuously.")

        def consume(position: int, frame_bytes: bytes):
            frame = self.resample_frame(frame_bytes)
            frame_start = round(position * SAMPLE_RATE / self.capture_rate)
            if self.buffer and frame_start - self.total_samples > FRAME_SAMPLES:
                self.finish_utterance()
                self.pre_roll.clear()
            self.total_samples = frame_start + len(frame)
            rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))
            speaking = rms >= self.args.energy_threshold
            if not self.buffer:
                self.pre_roll.append((frame_start, frame))
                if speaking:
                    self.buffer_start = self.pre_roll[0][0]
                    self.buffer = [item[1] for item in self.pre_roll]
                    self.pre_roll.clear()
                    self.silence = 0.0
                return
            self.buffer.append(frame)
            duration = (self.total_samples - self.buffer_start) / SAMPLE_RATE
            self.silence = 0.0 if speaking else self.silence + len(frame) / SAMPLE_RATE
            if self.silence >= self.args.silence_duration or duration >= self.args.max_speech:
                self.finish_utterance()
                self.pre_roll.clear()
            else:
                self.transcribe(final=False)

        try:
            recorder.start()
            while not self.stop_requested:
                error = recorder.error()
                if error:
                    raise RuntimeError(error)
                if dropped[0]:
                    print("\nLive captions fell behind. Full audio is still being saved.", file=sys.stderr)
                    dropped[0] = False
                try:
                    consume(*self.audio_queue.get(timeout=.2))
                except queue.Empty:
                    pass
                recorder.checkpoint()
        finally:
            recorder.stop()
            # Make saved audio playable even if the live model raised an exception.
            raw = self.output_dir / 'microphone.pcm'
            if raw.exists() and raw.stat().st_size:
                render_recording(self.output_dir)
        while not self.audio_queue.empty():
            consume(*self.audio_queue.get())
        self.finish_utterance()
        save_transcript(self.output_dir, self.segments)


def transcribe_file(args: argparse.Namespace, audio_path: Path) -> list[TranscriptSegment]:
    model = Model(
        args.final_model,
        models_dir=str(Path(args.models_dir).resolve()),
        language="bg",
        translate=False,
        print_progress=False,
        print_realtime=False,
        print_timestamps=False,
        no_context=False,
        suppress_blank=True,
        suppress_non_speech_tokens=True,
        temperature=0.0,
        n_threads=args.threads,
    )
    raw = model.transcribe(str(audio_path), language="bg", no_context=False)
    segments = merge_segments(raw)
    del model
    gc.collect()
    return segments


def transcript_for_llm(segments: list[TranscriptSegment]) -> str:
    return "\n".join(
        f"[{timestamp(s.start)}] {(s.speaker + ': ') if s.speaker else ''}{s.text}" for s in segments
    )


def minutes_schema() -> dict[str, Any]:
    task = {
        "type": "object",
        "properties": {
            "task": {"type": "string"},
            "owner": {"type": ["string", "null"]},
            "deadline": {"type": ["string", "null"]},
            "due_date": {"type": ["string", "null"]},
            "evidence_timestamp": {"type": "string"},
        },
        "required": ["task", "owner", "deadline", "due_date", "evidence_timestamp"],
        "additionalProperties": False,
    }
    item = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "evidence_timestamp": {"type": ["string", "null"]}},
        "required": ["text", "evidence_timestamp"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "array", "items": item},
            "decisions": {"type": "array", "items": item},
            "next_steps": {"type": "array", "items": item},
            "needs_decision": {"type": "array", "items": item},
            "tasks": {"type": "array", "items": task},
            "open_questions": {"type": "array", "items": item},
            "observations": {"type": "array", "items": item},
        },
        "required": ["summary", "decisions", "next_steps", "needs_decision", "tasks", "open_questions", "observations"],
        "additionalProperties": False,
    }


MARKER_NAMES = {"important": "Важно", "decision": "Решение", "check": "Провери"}


def llm_prompt(transcript: str, speakers: list[str] | None = None, meeting_date: str | None = None,
               markers: list[dict[str, Any]] | None = None) -> str:
    marked = ""
    if markers:
        lines = "\n".join(f"[{timestamp(m['time'])}] {MARKER_NAMES.get(m['kind'], m['kind'])}" + (f" — {m['note']}" if m.get("note") else "")
                          for m in markers[:100])
        marked = f"""
Моменти, отбелязани от потребителя по време на срещата. Те са подсказки къде да търсиш, не факти.
Провери всеки момент в текста и не измисляй решение само заради маркер.
{lines}
"""
    known = ""
    if speakers:
        names = "\n".join(f"- {name}" for name in speakers[:100])
        known = f"""
Известни участници (от предишни срещи). Ако текстът назовава някого от тях,
използвай точно това изписване за отговорник. Не приемай, че някой присъства, само защото е в списъка.
{names}
"""
    return f"""Ти си асистент за бележки от срещи. Анализирай само транскрипта по-долу.
Отговори на български. Не измисляй факти, имена, задачи или срокове.
Задача трябва да е изрично подкрепена от текста; обсъждана идея не е автоматично задача.
Ако отговорник или срок липсва, върни null. За всяка задача дай timestamp от текста.
Всеки елемент в summary, decisions, next_steps, needs_decision, open_questions и observations е обект:
text е твърдението, evidence_timestamp е timestamp на сегмента, който го доказва. Не пиши timestamp в text.
За решение посочи момента, в който решението е прието, а не момента, в който е предложено.
Обсъждана възможност не е решение. Върни null за evidence_timestamp само ако няма един конкретен момент.
Разграничавай решения, задачи и отворени въпроси. Върни само JSON по дадената схема.
Дата на срещата: {meeting_date or dt.date.today().isoformat()}. Ако срокът на задача може да се определи
като конкретна дата спрямо нея, попълни due_date във формат YYYY-MM-DD; иначе върни null.
next_steps: договорени следващи стъпки за процеса (например следваща среща); не повтаряй задачите.
needs_decision: въпроси, които изрично чакат решение от ръководител или възложител и не са решени.
observations: поверителни наблюдения за ръководителя след срещата: рискове, обещания, които изглеждат
нереалистични, колебание или скрито несъгласие. Всяко наблюдение има evidence_timestamp на казаното.
Не оценявай личности. Ако няма ясна основа в текста, върни празен списък.
{known}{marked}
ТРАНСКРИПТ:
{transcript}"""


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 600) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("The summarizer did not return JSON")
        return json.loads(match.group(0))


MINUTES_OPTIONAL = ("next_steps", "needs_decision", "observations")
# Every statement in these fields has a source moment and a review state, like a task.
ITEM_FIELDS = ("summary", "decisions", "next_steps", "needs_decision", "open_questions", "observations")
REVIEW_STATES = ("ai", "verified")
_CITED = re.compile(r"\s*[(\[](\d{2,}:\d{2}:\d{2})[)\]]")
_STAMP = re.compile(r"\b(\d{2,}:\d{2}:\d{2})\b")


# A mention in the notes points to its persistent task or decision, or waits for a person to link it.
REGISTRY_KEYS = ("item_id", "link")


def _check_registry_keys(mention: dict[str, Any]) -> None:
    if "item_id" in mention and (not isinstance(mention["item_id"], str) or not re.fullmatch(r"[a-f0-9]{1,64}", mention["item_id"])):
        raise ValueError("Invalid item ID")
    if "link" in mention and (not isinstance(mention["link"], dict) or not isinstance(mention["link"].get("candidates"), list)):
        raise ValueError("Invalid item link")


def note_item(value: Any) -> Any:
    """Notes saved before sources existed are plain text; a cited "(00:12:03)" becomes the source."""
    if not isinstance(value, str):
        return value
    cited = _CITED.search(value)
    if cited:
        return {"text": _CITED.sub("", value, count=1).strip(), "evidence_timestamp": cited.group(1), "review": "ai"}
    bare = _STAMP.search(value)
    return {"text": value.strip(), "evidence_timestamp": bare.group(1) if bare else None, "review": "ai"}


def validate_minutes(minutes: dict[str, Any], segments: list[TranscriptSegment] | None = None) -> None:
    """Validate notes. Fills in fields added after the first format, so older notes stay valid."""
    fields = {"summary", "decisions", "tasks", "open_questions"}
    if not isinstance(minutes, dict) or not fields <= set(minutes) or set(minutes) - fields - set(MINUTES_OPTIONAL):
        raise ValueError("Minutes must contain summary, decisions, tasks, and open_questions")
    for field in MINUTES_OPTIONAL:
        minutes.setdefault(field, [])
    fields |= set(MINUTES_OPTIONAL)
    for field in fields:
        if not isinstance(minutes[field], list):
            raise ValueError(f"{field} must be a list")
    evidence = {timestamp(s.start) for s in segments} if segments is not None else None
    for field in ITEM_FIELDS:
        minutes[field] = [note_item(item) for item in minutes[field]]
        for item in minutes[field]:
            if not isinstance(item, dict) or not {"text", "evidence_timestamp"} <= set(item) or set(item) - {"text", "evidence_timestamp", "review", *REGISTRY_KEYS}:
                raise ValueError(f"{field} items need text and a source timestamp field")
            item.setdefault("review", "ai")
            if not isinstance(item["text"], str) or not item["text"].strip():
                raise ValueError(f"{field} items need text")
            if item["review"] not in REVIEW_STATES:
                raise ValueError("Review state must be ai or verified")
            _check_registry_keys(item)
            stamp = item["evidence_timestamp"]
            if stamp is not None and (not isinstance(stamp, str) or not re.fullmatch(r"\d{2,}:\d{2}:\d{2}", stamp)):
                raise ValueError("Invalid evidence timestamp")
            if stamp is not None and evidence is not None and stamp not in evidence:
                raise ValueError(f"Timestamp {stamp} does not reference a transcript segment")
    for task in minutes["tasks"]:
        core = {"task", "owner", "deadline", "evidence_timestamp"}
        if not isinstance(task, dict) or not core <= set(task) or set(task) - core - {"due_date", "status", "review", *REGISTRY_KEYS}:
            raise ValueError("Invalid task fields")
        task.setdefault("due_date", None)
        task.setdefault("status", "open")
        task.setdefault("review", "ai")
        if task["review"] not in REVIEW_STATES:
            raise ValueError("Review state must be ai or verified")
        _check_registry_keys(task)
        if task["status"] not in {"open", "done"}:
            raise ValueError("Task status must be open or done")
        if task["due_date"] is not None:
            try:
                if not isinstance(task["due_date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", task["due_date"]):
                    raise ValueError
                dt.date.fromisoformat(task["due_date"])
            except ValueError:
                raise ValueError("Due date must be a date in YYYY-MM-DD format") from None
        if not isinstance(task["task"], str) or not task["task"].strip():
            raise ValueError("Task text is required")
        if any(task[k] is not None and not isinstance(task[k], str) for k in ["owner", "deadline"]):
            raise ValueError("Owner and deadline must be text or null")
        stamp = task["evidence_timestamp"]
        if not isinstance(stamp, str) or not re.fullmatch(r"\d{2,}:\d{2}:\d{2}", stamp):
            raise ValueError("Invalid evidence timestamp")
        if evidence is not None and stamp not in evidence:
            raise ValueError(f"Task timestamp {stamp} does not reference a transcript segment")


def generate_minutes(args: argparse.Namespace, segments: list[TranscriptSegment]) -> dict[str, Any]:
    transcript = transcript_for_llm(segments)
    if not transcript:
        raise ValueError("Cannot summarize an empty transcript")
    prompt = llm_prompt(transcript, getattr(args, "speakers", None), getattr(args, "meeting_date", None),
                        [m for m in getattr(args, "markers", None) or [] if segments[0].start - 5 <= m["time"] <= segments[-1].end + 5])
    schema = minutes_schema()
    stamps = list(dict.fromkeys(timestamp(s.start) for s in segments))
    schema["properties"]["tasks"]["items"]["properties"]["evidence_timestamp"]["enum"] = stamps
    for field in ITEM_FIELDS:
        schema["properties"][field]["items"]["properties"]["evidence_timestamp"]["enum"] = stamps + [None]
    if args.summarizer in {"local", "ollama"}:
        from app.local_ai import complete_json
        return complete_json(vars(args), [{"role": "user", "content": prompt}], schema, "meeting_minutes")
    if args.summarizer == "openai":
        key = getattr(args, "api_key", None) or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("Set OPENAI_API_KEY or use --summarizer local")
        response = post_json(
            "https://api.openai.com/v1/chat/completions",
            {
                "model": args.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "meeting_minutes", "strict": True, "schema": schema},
                },
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return extract_json(response["choices"][0]["message"]["content"])
    raise ValueError(f"Unknown summarizer: {args.summarizer}")


def save_minutes(output_dir: Path, minutes: dict[str, Any]) -> None:
    validate_minutes(minutes)
    atomic_text(output_dir / "minutes.json", 
        json.dumps(minutes, ensure_ascii=False, indent=2)
    )
    def line(item: dict[str, Any]) -> str:
        source = f" ({item['evidence_timestamp']})" if item.get("evidence_timestamp") else ""
        return f"- {item['text']}{source}" + (" — проверено" if item.get("review") == "verified" else "")
    lines = ["# Бележки от срещата", "", "## Резюме"]
    lines.extend(line(item) for item in minutes.get("summary", []))
    lines.extend(["", "## Взети решения"])
    decisions = minutes.get("decisions", [])
    lines.extend(line(item) for item in decisions) if decisions else lines.append("- Няма извлечени решения.")
    for field, heading in [("next_steps", "Следващи стъпки"), ("needs_decision", "Въпроси, изискващи решение")]:
        if minutes.get(field):
            lines.extend(["", f"## {heading}"])
            lines.extend(line(item) for item in minutes[field])
    lines.extend(["", "## Задачи", "", "| Задача | Отговорник | Краен срок | Дата | Статус | Източник |", "|---|---|---|---|---|---|"])
    for task in minutes.get("tasks", []):
        values = [task.get("task", ""), task.get("owner") or "Не е посочен", task.get("deadline") or "Не е посочен",
                  task.get("due_date") or "—", "Изпълнена" if task.get("status") == "done" else "Отворена", task.get("evidence_timestamp", "")]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    if not minutes.get("tasks"):
        lines.append("| Няма извлечени задачи | — | — | — | — | — |")
    lines.extend(["", "## Отворени въпроси"])
    questions = minutes.get("open_questions", [])
    lines.extend(line(item) for item in questions) if questions else lines.append("- Няма извлечени отворени въпроси.")
    atomic_text(output_dir / "minutes.md", "\n".join(lines) + "\n")


def postprocess(args: argparse.Namespace, output_dir: Path) -> None:
    audio_path = output_dir / "recording.wav"
    print(f"\nFinal accuracy pass with {args.final_model}…")
    segments = transcribe_file(args, audio_path)
    save_transcript(output_dir, segments)
    print(f"Saved: {output_dir / 'transcript.md'}")
    if args.summarizer != "none" and segments:
        print(f"Generating minutes with {args.summarizer} ({args.llm_model})…")
        minutes = generate_minutes(args, segments)
        validate_minutes(minutes, segments)
        save_minutes(output_dir, minutes)
        print(f"Saved: {output_dir / 'minutes.md'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["devices", "record", "finalize"], nargs="?", default="record")
    parser.add_argument("audio", nargs="?", type=Path, help="Existing 16 kHz mono WAV for finalize")
    parser.add_argument("--device", help="Input device number or name; defaults to iPhone when available")
    parser.add_argument("--output", type=Path, help="Output directory")
    parser.add_argument("--models-dir", default="models")
    parser.add_argument("--live-model", default="large-v3-turbo")
    parser.add_argument("--final-model", default="large-v3")
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--energy-threshold", type=float, default=0.008, help="RMS speech threshold; try 0.004–0.02")
    parser.add_argument("--silence-duration", type=float, default=0.75)
    parser.add_argument("--min-speech", type=float, default=0.45)
    parser.add_argument("--max-speech", type=float, default=12.0)
    parser.add_argument("--partial-interval", type=float, default=3.0)
    parser.add_argument("--pre-roll", type=float, default=0.45)
    parser.add_argument("--summarizer", choices=["none", "local", "openai", "ollama"], default="none")
    parser.add_argument("--llm-model", help="Cloud notes model (default gpt-4.1-mini)")
    parser.add_argument("--local-ai-base-url", default="http://localhost:1235/v1")
    parser.add_argument("--local-ai-model", default="qwen3.5-9b", help="Shared local text AI model ID")
    parser.add_argument("--local-ai-format", choices=["json_schema", "json_object", "text"], default="json_schema")
    parser.add_argument("--local-ai-max-tokens", type=int, default=4096)
    parser.add_argument("--local-ai-reasoning", choices=["default", "server", "none", "low", "medium", "high"], default="default")
    parser.add_argument("--no-final", action="store_true", help="Stop after live transcription")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.llm_model is None:
        args.llm_model = "gpt-4.1-mini"
    if args.command == "devices":
        list_devices()
        return 0
    if args.command == "finalize":
        if not args.audio:
            parser.error("finalize requires an audio file")
        args.output = args.output or args.audio.parent
        args.output.mkdir(parents=True, exist_ok=True)
        if args.audio.resolve() != (args.output / "recording.wav").resolve():
            samples = read_wav(args.audio)
            write_wav(args.output / "recording.wav", samples)
        postprocess(args, args.output)
        return 0

    device = find_device(args.device)
    output_dir = args.output or Path("output") / dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    live = LiveMeeting(args, output_dir)

    def stop_handler(signum: int, frame: Any) -> None:
        live.stop_requested = True

    previous_handler = signal.signal(signal.SIGINT, stop_handler)
    try:
        live.run(device)
        del live.model
        gc.collect()
        if not args.no_final and (output_dir / "recording.wav").stat().st_size > 44:
            postprocess(args, output_dir)
        elif args.summarizer != "none" and live.segments:
            minutes = generate_minutes(args, live.segments)
            validate_minutes(minutes, live.segments)
            save_minutes(output_dir, minutes)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    print(f"Output: {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
