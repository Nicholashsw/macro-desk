"""Speak Macro Desk on a Sonos speaker.

    macro-desk-sonos discover                 # list speakers, plays nothing
    macro-desk-sonos say "Testing, one two"   # short test clip
    macro-desk-sonos brief                    # latest macro briefing
    macro-desk-sonos brief --dry-run          # render the audio file only
    macro-desk-sonos brief --yes --skip-if-playing   # unattended, for a schedule

Playback asks for confirmation unless --yes is passed. The audio is rendered on
this Mac with ``say``, served on MACRO_DESK_CLIP_PORT (default 8765) and fetched
by the speaker over the local network.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import sonos
from .catalog import INDICATORS
from .clipserver import ClipServer, local_ip_for
from .data import FredStore
from .desk import Desk
from .tts import SayTTS, duration_seconds

KEEP_CLIPS = 5


def audio_dir() -> Path:
    return Path(os.getenv("MACRO_DESK_AUDIO_DIR", Path.home() / ".cache" / "macro-desk"))


def latest_briefing(store: FredStore | None = None) -> tuple[str, str]:
    """Briefing text after a live FRED refresh, and where the data came from."""
    store = store or FredStore()
    ids = sorted({i.series_id for i in INDICATORS.values()})
    store.prime(ids)
    store.refresh(ids)  # waits for FRED; a failed fetch keeps the snapshot copy
    text = Desk(store).briefing()["speech"]
    sources = {store.get(s).source for s in ids}
    source = "live" if sources == {"live"} else "snapshot" if "live" not in sources else "mixed"
    return text, source


def render(text: str, stem: str, tts=None) -> Path:
    folder = audio_dir()
    out = folder / f"{stem}-{datetime.now():%Y%m%d-%H%M%S}.wav"
    (tts or SayTTS()).render(text, out)
    for old in sorted(folder.glob(f"{stem}-*.wav"))[:-KEEP_CLIPS]:
        old.unlink(missing_ok=True)
    return out


def confirm(question: str, assume_yes: bool, ask: Callable[[str], str] = input) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Not running in a terminal, so playback needs --yes.")
        return False
    return ask(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def play(path: Path, args: argparse.Namespace, title: str) -> int:
    speaker = sonos.find_speaker(args.speaker, args.ip)
    if args.skip_if_playing and sonos.is_playing(speaker):
        print(f"{speaker.player_name} is already playing something, skipping.")
        return 0
    volume = args.volume if args.volume is not None else _env_int("MACRO_DESK_SONOS_VOLUME")
    level = f"volume {volume}" if volume is not None else f"current volume ({speaker.volume})"
    seconds = duration_seconds(path)
    if not confirm(f"Play {seconds:.0f}s clip on '{speaker.player_name}' at {level}?", args.yes):
        print("Cancelled.")
        return 1
    host = local_ip_for(speaker.ip_address)
    port = args.port if args.port is not None else int(os.getenv("MACRO_DESK_CLIP_PORT", "8765"))
    with ClipServer(path, advertise_host=host, port=port) as server:
        print(f"Playing on {speaker.player_name} from {server.url}")
        ok = sonos.play_clip(speaker, server.url, seconds, title=title, volume=volume)
    if not ok:
        print(f"{speaker.player_name} never started the clip. Check the macOS firewall allows "
              f"incoming connections for Python on port {port}.")
        return 2
    print("Done.")
    return 0


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    return int(raw) if raw else None


def cmd_discover(args: argparse.Namespace) -> int:
    speakers = sonos.list_speakers()
    if not speakers:
        print("No Sonos speakers found. The Mac must be on the same Wi-Fi as the speaker.")
        return 1
    for s in speakers:
        grouped = "" if s["coordinator"] == s["name"] else f", grouped under {s['coordinator']}"
        print(f"{s['name']:<20} {s['ip']:<16} {s['model']}, volume {s['volume']}{grouped}")
    return 0


def cmd_say(args: argparse.Namespace) -> int:
    path = render(args.text, "say")
    print(f"Rendered {path} ({duration_seconds(path):.0f}s)")
    return 0 if args.dry_run else play(path, args, "Macro Desk")


def cmd_brief(args: argparse.Namespace) -> int:
    text, source = latest_briefing()
    if source != "live":
        print(f"FRED was not fully reachable; using {source} data.")
    path = render(text, "briefing")
    print(f"Rendered {path} ({duration_seconds(path):.0f}s)\n{text}")
    return 0 if args.dry_run else play(path, args, "Macro briefing")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="macro-desk-sonos", description="Speak Macro Desk on a Sonos speaker.")
    sub = p.add_subparsers(dest="command", required=True)

    playback = argparse.ArgumentParser(add_help=False)
    playback.add_argument("--speaker", help="room name, defaults to MACRO_DESK_SONOS_NAME")
    playback.add_argument("--ip", help="speaker IP, skips discovery")
    playback.add_argument("--volume", type=int, help="0-100 for the clip; restored afterwards")
    playback.add_argument("--port", type=int, help="port the clip is served on (default 8765)")
    playback.add_argument("--yes", action="store_true", help="play without asking")
    playback.add_argument("--dry-run", action="store_true", help="render the audio file only")
    playback.add_argument("--skip-if-playing", action="store_true", help="do nothing if music is on")

    sub.add_parser("discover", help="list Sonos speakers on this network").set_defaults(fn=cmd_discover)
    say = sub.add_parser("say", parents=[playback], help="speak a line of text")
    say.add_argument("text")
    say.set_defaults(fn=cmd_say)
    sub.add_parser("brief", parents=[playback], help="speak the latest macro briefing").set_defaults(fn=cmd_brief)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except (sonos.SpeakerNotFound, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
