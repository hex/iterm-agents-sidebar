"""The daemon plays the panel's two sounds, so a page reload cannot silence them.

Ways it could go wrong, each covered below:
- a kind other than "blocked" or "done" plays something;
- a sound plays with Sound off, with its own switch off, or at volume 0;
- two pages (a Toolbelt per window) report one moment and it plays twice,
  even when both requests land before either player has started;
- a player that cannot start keeps its moment reserved, so it never plays;
- a player that fails, or a missing tone file, fails silently;
- a burst of sessions starts an unbounded pile of players;
- the tone files are half-written when a player opens them, or come out
  with the wrong shape (length, a second note, silence).
"""
import asyncio
import os
import stat
import wave

import pytest

import sound


def player_script(tmp_path, body):
    """A real executable in place of afplay, which records how it was run."""
    script = tmp_path / "player"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def recording_player(tmp_path, seconds=0.0):
    calls = tmp_path / "calls"
    return player_script(tmp_path, f'echo "$@" >> "{calls}"\nsleep {seconds}'), calls


ON = {"sound": True, "sound_blocked": True, "sound_done": True, "volume": 0.9}


class Log(list):
    def __call__(self, *words):
        self.append(" ".join(str(w) for w in words))


def run(coro):
    return asyncio.run(coro)


def test_the_tones_are_written_whole_and_shaped_like_the_page_ones(tmp_path):
    written = sound.write_tones(tmp_path)
    assert sorted(written) == ["blocked", "done"]
    for kind, low, high in (("blocked", 0.40, 0.44), ("done", 0.35, 0.38)):
        with wave.open(str(written[kind])) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 44100)
            assert low <= w.getnframes() / 44100 <= high, kind
            frames = w.readframes(w.getnframes())
        peak = max(abs(int.from_bytes(frames[i:i + 2], "little", signed=True))
                   for i in range(0, len(frames), 2))
        assert peak > 1000, kind
    # Written through a temporary file, so nothing but the two tones is left.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["blocked.wav", "done.wav"]


def test_the_blocked_tone_rises_through_a_second_note(tmp_path):
    written = sound.write_tones(tmp_path)
    with wave.open(str(written["blocked"])) as w:
        frames = w.readframes(w.getnframes())
    samples = [int.from_bytes(frames[i:i + 2], "little", signed=True) for i in range(0, len(frames), 2)]

    def pitch(start, end):
        crossings = sum(1 for a, b in zip(samples[start:end], samples[start + 1:end]) if a < 0 <= b)
        return crossings / ((end - start) / 44100)

    assert 640 <= pitch(int(.02 * 44100), int(.12 * 44100)) <= 680
    assert 860 <= pitch(int(.20 * 44100), int(.30 * 44100)) <= 900


def test_a_sound_plays_its_own_tone_at_the_set_volume(tmp_path):
    player, calls = recording_player(tmp_path)
    tones = sound.write_tones(tmp_path / "tones")
    log = Log()
    played = run(sound.Player(tones, log, player=str(player)).play("s1", "blocked", ON))
    assert played is True
    assert calls.read_text() == f"-v 0.9 {tones['blocked']}\n"
    assert log == []


@pytest.mark.parametrize("settings", [
    {**ON, "sound": False},
    {**ON, "sound_done": False},
    {**ON, "volume": 0.0},
])
def test_no_sound_when_the_settings_say_none(tmp_path, settings):
    player, calls = recording_player(tmp_path)
    tones = sound.write_tones(tmp_path / "tones")
    assert run(sound.Player(tones, Log(), player=str(player)).play("s1", "done", settings)) is False
    assert not calls.exists()


def test_a_kind_that_is_not_one_of_the_two_is_refused(tmp_path):
    player, calls = recording_player(tmp_path)
    tones = sound.write_tones(tmp_path / "tones")
    log = Log()
    assert run(sound.Player(tones, log, player=str(player)).play("s1", "../x", ON)) is False
    assert not calls.exists()
    assert log == ["sound refused: kind '../x' is not one of blocked, done"]


def test_one_moment_reported_by_two_pages_at_once_plays_once(tmp_path):
    player, calls = recording_player(tmp_path)
    tones = sound.write_tones(tmp_path / "tones")
    box = sound.Player(tones, Log(), player=str(player))

    async def both():
        return await asyncio.gather(box.play("s1", "done", ON), box.play("s1", "done", ON))

    assert sorted(run(both())) == [False, True]
    assert calls.read_text().count("\n") == 1


def test_the_same_moment_plays_again_once_the_window_has_passed(tmp_path):
    player, calls = recording_player(tmp_path)
    tones = sound.write_tones(tmp_path / "tones")
    now = [100.0]
    box = sound.Player(tones, Log(), player=str(player), clock=lambda: now[0])
    assert run(box.play("s1", "done", ON)) is True
    now[0] += sound.REPEAT_WINDOW - 0.1
    assert run(box.play("s1", "done", ON)) is False
    now[0] += 0.2
    assert run(box.play("s1", "done", ON)) is True
    # Another session, or the other kind, is its own moment.
    assert run(box.play("s2", "done", ON)) is True
    assert run(box.play("s1", "blocked", ON)) is True
    assert calls.read_text().count("\n") == 4


def test_a_player_that_cannot_start_is_logged_and_frees_its_moment(tmp_path):
    tones = sound.write_tones(tmp_path / "tones")
    log = Log()
    box = sound.Player(tones, log, player=str(tmp_path / "no-such-player"))
    assert run(box.play("s1", "done", ON)) is False
    assert len(log) == 1 and log[0].startswith("sound done: cannot start ") and "No such file" in log[0]
    player, _ = recording_player(tmp_path)
    box.player = str(player)
    assert run(box.play("s1", "done", ON)) is True


def test_a_player_that_fails_is_logged_with_what_it_said(tmp_path):
    player = player_script(tmp_path, 'echo "no audio device" >&2\nexit 3')
    tones = sound.write_tones(tmp_path / "tones")
    log = Log()
    assert run(sound.Player(tones, log, player=str(player)).play("s1", "blocked", ON)) is True
    assert log == ["sound blocked: player exited 3: no audio device"]


def test_a_missing_tone_file_is_logged_rather_than_played(tmp_path):
    player, calls = recording_player(tmp_path)
    tones = sound.write_tones(tmp_path / "tones")
    os.remove(tones["done"])
    log = Log()
    assert run(sound.Player(tones, log, player=str(player)).play("s1", "done", ON)) is False
    assert not calls.exists()
    assert log == [f"sound done: no tone at {tones['done']}"]


def test_no_more_than_two_play_at_once(tmp_path):
    player, calls = recording_player(tmp_path, seconds=0.5)
    tones = sound.write_tones(tmp_path / "tones")
    log = Log()
    box = sound.Player(tones, log, player=str(player))

    async def burst():
        return await asyncio.gather(*(box.play(f"s{i}", "done", ON) for i in range(4)))

    assert sorted(run(burst())) == [False, False, True, True]
    assert calls.read_text().count("\n") == 2
    assert log == ["sound done: 2 already playing, skipped"] * 2


def test_tones_that_cannot_be_written_leave_the_panel_running_and_say_why(tmp_path):
    blocker = tmp_path / "tones"
    blocker.write_text("a file where the directory should be")
    log = Log()
    box = sound.Player.for_dir(blocker, log)
    assert len(log) == 1 and log[0].startswith(f"sound off: cannot write tones in {blocker}: ")
    assert run(box.play("s1", "done", ON)) is False
    assert log[1:] == [f"sound done: no tone at {blocker / 'done.wav'}"]
