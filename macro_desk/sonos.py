"""Play short clips on a Sonos speaker over the local network.

Uses SoCo (``pip install -e ".[sonos]"``), which talks to the speaker's UPnP
interface on port 1400. No Sonos account or cloud API is involved. Whatever was
playing is snapshotted first and restored after the clip, volume included.

    MACRO_DESK_SONOS_NAME=Bedroom    # pick a speaker by room name
    MACRO_DESK_SONOS_IP=192.168.1.40 # or skip discovery entirely
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

DISCOVERY_TIMEOUT = 5.0
START_TIMEOUT = 15.0  # seconds to wait for the player to start fetching the clip
END_SLACK = 15.0  # extra seconds past the clip length before giving up on it


class SpeakerNotFound(RuntimeError):
    pass


def _soco():
    try:
        import soco
    except ImportError as exc:
        raise RuntimeError('SoCo is not installed. Run: pip install -e ".[sonos]"') from exc
    return soco


def find_speaker(name: str | None = None, ip: str | None = None, timeout: float = DISCOVERY_TIMEOUT) -> Any:
    soco = _soco()
    name = name or os.getenv("MACRO_DESK_SONOS_NAME") or None
    ip = ip or os.getenv("MACRO_DESK_SONOS_IP") or None
    if ip:
        return soco.SoCo(ip)
    devices = sorted(soco.discover(timeout=timeout) or [], key=lambda d: d.player_name)
    if not devices:
        raise SpeakerNotFound(
            "No Sonos speakers answered. Check the Mac is on the same Wi-Fi as the speaker "
            "(not a guest or campus network), or set MACRO_DESK_SONOS_IP.")
    if name:
        for d in devices:
            if d.player_name.lower() == name.lower():
                return d
        raise SpeakerNotFound(f"No speaker named '{name}'. Found: {', '.join(d.player_name for d in devices)}.")
    if len(devices) > 1:
        raise SpeakerNotFound(
            f"Found {len(devices)} speakers ({', '.join(d.player_name for d in devices)}). "
            "Choose one with --speaker or MACRO_DESK_SONOS_NAME.")
    return devices[0]


def describe(speaker: Any) -> dict:
    info = speaker.get_speaker_info()
    return {"name": speaker.player_name, "ip": speaker.ip_address, "model": info.get("model_name", ""),
            "volume": speaker.volume, "coordinator": coordinator(speaker).player_name}


def list_speakers(timeout: float = DISCOVERY_TIMEOUT) -> list[dict]:
    soco = _soco()
    return [describe(d) for d in sorted(soco.discover(timeout=timeout) or [], key=lambda d: d.player_name)]


def coordinator(speaker: Any) -> Any:
    """Grouped speakers only accept playback commands through their group coordinator."""
    group = speaker.group
    return group.coordinator if group is not None else speaker


def state(speaker: Any) -> str:
    return speaker.get_current_transport_info()["current_transport_state"]


def is_playing(speaker: Any) -> bool:
    return state(coordinator(speaker)) == "PLAYING"


def _default_snapshot(device: Any) -> Any:
    from soco.snapshot import Snapshot

    return Snapshot(device)


def play_clip(speaker: Any, url: str, seconds: float, title: str = "Macro briefing",
              volume: int | None = None, resume: bool = True,
              snapshot_factory: Callable[[Any], Any] = _default_snapshot,
              sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic, poll: float = 0.5) -> bool:
    """Play ``url`` and block until it finishes. Returns False if it never started."""
    target = coordinator(speaker)
    snap = snapshot_factory(target) if resume else None
    if snap is not None:
        snap.snapshot()
    before = speaker.volume
    started = False
    try:
        if volume is not None:
            speaker.volume = max(0, min(100, int(volume)))
        target.play_uri(url, title=title)

        deadline = clock() + START_TIMEOUT
        while clock() < deadline:
            if state(target) == "PLAYING":
                started = True
                break
            sleep(poll)
        if started:
            deadline = clock() + seconds + END_SLACK
            while clock() < deadline and state(target) in ("PLAYING", "TRANSITIONING"):
                sleep(poll)
    finally:
        if snap is not None:
            snap.restore(fade=False)
        speaker.volume = before
    return started
