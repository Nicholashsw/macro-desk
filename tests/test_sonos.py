"""Sonos playback path, offline: fake speakers, fake text to speech, real HTTP clip server."""

import argparse
import os
import sys
import types
import wave
from pathlib import Path

import httpx
import pytest

os.environ["MACRO_DESK_OFFLINE"] = "1"

from macro_desk import sonos, sonos_cli  # noqa: E402
from macro_desk.clipserver import ClipServer  # noqa: E402
from macro_desk.data import FredStore  # noqa: E402
from macro_desk.desk import Desk  # noqa: E402
from macro_desk.tts import SayTTS, duration_seconds  # noqa: E402


class FakeSpeaker:
    def __init__(self, name="Bedroom", ip="192.168.1.40", states=("PLAYING", "PLAYING", "STOPPED"), volume=30):
        self.player_name, self.ip_address, self.volume = name, ip, volume
        self.states = list(states)
        self.played = []
        self.volume_log = []
        self.group = None

    def __setattr__(self, key, value):
        if key == "volume" and "volume_log" in self.__dict__:
            self.volume_log.append(value)
        super().__setattr__(key, value)

    def play_uri(self, uri, title=""):
        self.played.append((uri, title))

    def get_current_transport_info(self):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"current_transport_state": state}

    def get_speaker_info(self):
        return {"model_name": "Sonos One"}


class FakeSnapshot:
    def __init__(self, device):
        self.device, self.events = device, []

    def snapshot(self):
        self.events.append("snapshot")

    def restore(self, fade=False):
        self.events.append("restore")


def fake_clock():
    t = [0.0]

    def clock():
        t[0] += 1.0
        return t[0]

    return clock


def write_wav(path: Path, seconds: float = 2.0, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


class FakeTTS:
    def __init__(self):
        self.texts = []

    def render(self, text, out):
        self.texts.append(text)
        return write_wav(out)


# -- play_clip ---------------------------------------------------------------

def test_play_clip_restores_music_and_volume():
    spk = FakeSpeaker(volume=30)
    snaps = []
    ok = sonos.play_clip(spk, "http://mac/clip.wav", seconds=2, volume=45,
                         snapshot_factory=lambda d: snaps.append(FakeSnapshot(d)) or snaps[-1],
                         sleep=lambda _: None, clock=fake_clock())
    assert ok
    assert spk.played == [("http://mac/clip.wav", "Macro briefing")]
    assert snaps[0].events == ["snapshot", "restore"]
    assert spk.volume_log == [45, 30]


def test_grouped_speaker_plays_through_coordinator():
    leader, member = FakeSpeaker("Living Room"), FakeSpeaker("Bedroom")
    member.group = types.SimpleNamespace(coordinator=leader)
    snaps = []
    sonos.play_clip(member, "http://mac/clip.wav", seconds=2,
                    snapshot_factory=lambda d: snaps.append(d) or FakeSnapshot(d),
                    sleep=lambda _: None, clock=fake_clock())
    assert leader.played and not member.played
    assert snaps == [leader]


def test_clip_that_never_starts_still_restores():
    spk = FakeSpeaker(states=("STOPPED",), volume=20)
    snap = FakeSnapshot(spk)
    ok = sonos.play_clip(spk, "http://mac/clip.wav", seconds=2, volume=50,
                         snapshot_factory=lambda d: snap, sleep=lambda _: None, clock=fake_clock())
    assert not ok
    assert snap.events == ["snapshot", "restore"]
    assert spk.volume == 20


def test_resume_off_skips_snapshot():
    def boom(_):
        raise AssertionError("snapshot should not be taken")

    sonos.play_clip(FakeSpeaker(), "http://mac/clip.wav", seconds=2, resume=False,
                    snapshot_factory=boom, sleep=lambda _: None, clock=fake_clock())


# -- clip server -------------------------------------------------------------

def test_clip_server_serves_only_its_file(tmp_path):
    clip = write_wav(tmp_path / "briefing.wav")
    (tmp_path / "secret.txt").write_text("nope")
    with ClipServer(clip, advertise_host="127.0.0.1", bind="127.0.0.1") as srv:
        assert srv.url.startswith("http://127.0.0.1:") and srv.url.endswith("-briefing.wav")
        got = httpx.get(srv.url)
        assert got.status_code == 200
        assert got.headers["content-type"] == "audio/wav"
        assert got.content == clip.read_bytes()
        assert httpx.head(srv.url).headers["content-length"] == str(clip.stat().st_size)
        base = srv.url.rsplit("/", 1)[0]
        for path in ("/briefing.wav", "/secret.txt", "/../secret.txt", "/"):
            assert httpx.get(base + path).status_code == 404


# -- discovery ---------------------------------------------------------------

@pytest.fixture
def fake_soco(monkeypatch):
    found = []
    mod = types.ModuleType("soco")
    mod.discover = lambda timeout=5: set(found)
    mod.SoCo = lambda ip: FakeSpeaker("By IP", ip)
    monkeypatch.setitem(sys.modules, "soco", mod)
    monkeypatch.delenv("MACRO_DESK_SONOS_NAME", raising=False)
    monkeypatch.delenv("MACRO_DESK_SONOS_IP", raising=False)
    return found


def test_find_speaker_by_ip_skips_discovery(fake_soco):
    assert sonos.find_speaker(ip="10.0.0.9").ip_address == "10.0.0.9"


def test_find_single_speaker(fake_soco):
    fake_soco.append(FakeSpeaker("Bedroom"))
    assert sonos.find_speaker().player_name == "Bedroom"


def test_find_speaker_by_name_is_case_insensitive(fake_soco):
    fake_soco.extend([FakeSpeaker("Bedroom"), FakeSpeaker("Kitchen", "192.168.1.41")])
    assert sonos.find_speaker(name="kitchen").player_name == "Kitchen"


def test_several_speakers_need_a_name(fake_soco):
    fake_soco.extend([FakeSpeaker("Bedroom"), FakeSpeaker("Kitchen", "192.168.1.41")])
    with pytest.raises(sonos.SpeakerNotFound, match="Bedroom, Kitchen"):
        sonos.find_speaker()


def test_no_speakers_explains_the_network(fake_soco):
    with pytest.raises(sonos.SpeakerNotFound, match="same Wi-Fi"):
        sonos.find_speaker()


# -- briefing and CLI --------------------------------------------------------

def test_spoken_briefing_matches_the_mcp_tool():
    store = FredStore(offline=True)
    text, source = sonos_cli.latest_briefing(store)
    assert text == Desk(store).briefing()["speech"]
    assert source == "snapshot"


def test_say_reads_text_from_a_file_not_argv(tmp_path):
    cmd = SayTTS(voice="Ava", rate=180).command(tmp_path / "t.txt", tmp_path / "o.wav")
    assert cmd[:3] == ["say", "--file-format=WAVE", "--data-format=LEI16@44100"]
    assert cmd[cmd.index("-f") + 1] == str(tmp_path / "t.txt")
    assert cmd[cmd.index("-v") + 1] == "Ava" and cmd[cmd.index("-r") + 1] == "180"


def test_render_keeps_only_recent_clips(tmp_path, monkeypatch):
    monkeypatch.setenv("MACRO_DESK_AUDIO_DIR", str(tmp_path))
    for i in range(7):
        write_wav(tmp_path / f"briefing-20260101-00000{i}.wav")
    out = sonos_cli.render("Hello.", "briefing", tts=FakeTTS())
    remaining = sorted(tmp_path.glob("briefing-*.wav"))
    assert len(remaining) == sonos_cli.KEEP_CLIPS and out in remaining
    assert duration_seconds(out) == pytest.approx(2.0)


def test_playback_needs_confirmation_off_a_terminal(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert not sonos_cli.confirm("Play?", assume_yes=False)
    assert sonos_cli.confirm("Play?", assume_yes=True)


def test_confirmation_prompt(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert sonos_cli.confirm("Play?", False, ask=lambda _: "y")
    assert not sonos_cli.confirm("Play?", False, ask=lambda _: "")


def _args(**kw):
    base = dict(speaker=None, ip=None, volume=None, port=0, yes=True, dry_run=False, skip_if_playing=False)
    return argparse.Namespace(**{**base, **kw})


def test_skip_if_playing_leaves_music_alone(tmp_path, monkeypatch):
    spk = FakeSpeaker(states=("PLAYING",))
    monkeypatch.setattr(sonos, "find_speaker", lambda *a, **k: spk)
    assert sonos_cli.play(write_wav(tmp_path / "c.wav"), _args(skip_if_playing=True), "t") == 0
    assert spk.played == []


def test_play_serves_clip_to_the_speaker(tmp_path, monkeypatch):
    spk = FakeSpeaker(ip="127.0.0.1")
    fetched = []

    def fake_play(speaker, url, seconds, title, volume):
        fetched.append(httpx.get(url).status_code)
        return True

    monkeypatch.setattr(sonos, "find_speaker", lambda *a, **k: spk)
    monkeypatch.setattr(sonos, "play_clip", fake_play)
    assert sonos_cli.play(write_wav(tmp_path / "c.wav"), _args(volume=25), "t") == 0
    assert fetched == [200]


def test_brief_dry_run_never_touches_sonos(tmp_path, monkeypatch):
    monkeypatch.setenv("MACRO_DESK_AUDIO_DIR", str(tmp_path))
    tts = FakeTTS()
    monkeypatch.setattr(sonos_cli, "SayTTS", lambda: tts)
    monkeypatch.setattr(sonos, "find_speaker", lambda *a, **k: pytest.fail("dry run contacted Sonos"))
    assert sonos_cli.main(["brief", "--dry-run"]) == 0
    assert tts.texts[0].startswith("Here's your macro briefing.")
    assert list(tmp_path.glob("briefing-*.wav"))
