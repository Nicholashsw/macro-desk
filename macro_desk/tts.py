"""Text to speech for local playback.

The default backend is macOS ``say``: built in, offline and free. It writes
16-bit PCM WAV at 44.1 kHz, a format every Sonos player streams.

    MACRO_DESK_VOICE=Ava  MACRO_DESK_RATE=185   # optional voice and words per minute
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Protocol


class TTS(Protocol):
    def render(self, text: str, out: Path) -> Path: ...


class SayTTS:
    def __init__(self, voice: str | None = None, rate: int | None = None):
        self.voice = voice or os.getenv("MACRO_DESK_VOICE") or None
        self.rate = rate or int(os.getenv("MACRO_DESK_RATE", "0")) or None

    def command(self, text_file: Path, out: Path) -> list[str]:
        cmd = ["say", "--file-format=WAVE", "--data-format=LEI16@44100", "-o", str(out), "-f", str(text_file)]
        if self.voice:
            cmd += ["-v", self.voice]
        if self.rate:
            cmd += ["-r", str(self.rate)]
        return cmd

    def render(self, text: str, out: Path) -> Path:
        if shutil.which("say") is None:
            raise RuntimeError("macOS 'say' was not found. Speech rendering needs a Mac.")
        out.parent.mkdir(parents=True, exist_ok=True)
        # Read from a file rather than argv so text starting with "-" is never taken as a flag.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(text)
            text_file = Path(fh.name)
        try:
            subprocess.run(self.command(text_file, out), check=True, capture_output=True, timeout=180)
        finally:
            text_file.unlink(missing_ok=True)
        return out


def duration_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())
