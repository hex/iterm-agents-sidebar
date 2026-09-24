# ABOUTME: The panel's two sounds, played by the daemon: tones written once as WAV files,
# ABOUTME: then afplay per moment, one play per session and kind however many pages report it.
import asyncio
import math
import os
import struct
import tempfile
import time
import wave
from pathlib import Path

RATE = 44100

#: Each tone as (hz, start s, length s) steps and a peak gain, as the page
#: once synthesised them: a rising pair asks, a single soft note ends.
TONES = {
    "blocked": ([(660, 0, .16), (880, .13, .26)], .22),
    "done": ([(520, 0, .34)], .10),
}

#: Short enough that a real second moment still sounds, long enough to take
#: in the same moment reported by every window's page.
REPEAT_WINDOW = 3.0

#: A burst of sessions changing at once is one sound's worth of news; more
#: players than this would only be noise on top of noise.
MAX_PLAYING = 2

PLAYER = "/usr/bin/afplay"

# A short attack and an exponential tail, from and to this floor: a click on
# either end is what makes a synthesised tone sound cheap.
ATTACK = .012
FLOOR = .0001
TAIL = .02


def render(steps, gain):
    """One tone as signed 16-bit mono PCM, its notes summed where they overlap."""
    end = max(at + length + TAIL for _, at, length in steps)
    samples = [0.0] * int(end * RATE)
    for hz, at, length in steps:
        start = int(at * RATE)
        for i in range(int((length + TAIL) * RATE)):
            t = i / RATE
            if t < ATTACK:
                level = FLOOR * (gain / FLOOR) ** (t / ATTACK)
            elif t < length:
                level = gain * (FLOOR / gain) ** ((t - ATTACK) / (length - ATTACK))
            else:
                level = 0.0
            samples[start + i] += level * math.sin(2 * math.pi * hz * t)
    return b"".join(struct.pack("<h", round(max(-1.0, min(1.0, v)) * 32767)) for v in samples)


def tone_paths(directory):
    return {kind: Path(directory) / f"{kind}.wav" for kind in TONES}


def write_tones(directory):
    """Write each tone to <directory>/<kind>.wav. -> {kind: path}.

    Through a temporary file in the same directory and a rename, so a player
    never opens a tone half-written.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = tone_paths(directory)
    for kind, (steps, gain) in TONES.items():
        fd, scratch = tempfile.mkstemp(dir=directory, prefix=f".{kind}-", suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as fh, wave.open(fh, "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(RATE)
                out.writeframes(render(steps, gain))
            os.replace(scratch, paths[kind])
        except BaseException:
            os.unlink(scratch)
            raise
    return paths


class Player:
    """Plays a moment's tone once, whichever page reports it and however often."""

    def __init__(self, tones, log, player=PLAYER, clock=time.monotonic):
        self.tones = tones
        self.log = log
        self.player = player
        self.clock = clock
        self.last_played = {}
        self.playing = 0

    @classmethod
    def for_dir(cls, directory, log):
        """A player for tones written now into `directory`.

        A tone that cannot be written turns sound off and says why; it never
        stops the panel, which is worth more than its sounds.
        """
        try:
            tones = write_tones(directory)
        except OSError as error:
            log(f"sound off: cannot write tones in {directory}: {error}")
            tones = tone_paths(directory)
        return cls(tones, log)

    async def play(self, session_id, kind, settings):
        """-> whether a player was started for this moment."""
        if kind not in TONES:
            self.log(f"sound refused: kind {kind!r} is not one of {', '.join(TONES)}")
            return False
        volume = settings["volume"]
        if not (settings["sound"] and settings[f"sound_{kind}"] and volume > 0):
            return False
        tone = self.tones[kind]
        if not tone.is_file():
            self.log(f"sound {kind}: no tone at {tone}")
            return False
        if self.playing >= MAX_PLAYING:
            self.log(f"sound {kind}: {self.playing} already playing, skipped")
            return False

        # Reserved before the first await, so a second page's report of the
        # same moment, arriving while this one starts its player, finds it.
        now = self.clock()
        for key, at in list(self.last_played.items()):
            if now - at >= REPEAT_WINDOW:
                del self.last_played[key]
        key = (session_id, kind)
        if key in self.last_played:
            return False
        self.last_played[key] = now
        self.playing += 1
        try:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.player, "-v", f"{volume:g}", str(tone),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE)
            except OSError as error:
                del self.last_played[key]
                self.log(f"sound {kind}: cannot start {self.player}: {error}")
                return False
            _, said = await proc.communicate()
            if proc.returncode:
                text = said.decode(errors="replace").strip()
                self.log(f"sound {kind}: player exited {proc.returncode}: {text}")
            return True
        finally:
            self.playing -= 1
