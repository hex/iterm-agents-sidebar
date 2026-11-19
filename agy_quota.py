#!/usr/bin/env python3.10
# ABOUTME: Antigravity CLI quota for the Agents panel, read by running `agy -p /quota` now and then.
# ABOUTME: agy asks Google on its own login; the panel never reads, keeps or sends that login itself.
"""agy prints its quota as JSON in print mode, with no model turn and no tokens spent.

`agy -p /quota --output-format json` answers with the account's quota groups
(Gemini models, Claude and GPT models, a model with an allowance of its own),
each with its windows: how much of it is left and when it fully refreshes.
A run that fails, whatever its exit code, keeps the last figures with the
time they were read.
"""
import json
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import threading

from accounts import DAY_SECONDS, _epoch, pace

#: Where agy's installer puts it, then the package managers' bins: the daemon
#: starts from iTerm2 without a login shell's PATH.
AGY_PATHS = ("~/.local/bin/agy", "/opt/homebrew/bin/agy", "/usr/local/bin/agy")
#: How often to ask while readings succeed; each ask starts agy for about three seconds.
READ_SECONDS = 5 * 60
#: The longest gap between asks while the figures hold still.
QUIET_READ_SECONDS = 30 * 60
#: A press of reload asks again unless the last ask is this recent.
RELOAD_FLOOR_SECONDS = 60
#: agy loads its tools and logs in before it answers; past this it is stuck.
TIMEOUT_SECONDS = 60
#: How much of agy's own message a log line keeps.
REASON_CHARS = 200
#: agy treats the folder it starts in as a project and reads its
#: .agents/hooks.json, so each run starts in a new empty folder under this
#: one, which the panel owns.
AGY_FOLDER = os.path.expanduser("~/.local/share/agents-sidebar/agy")

#: The window names agy uses -> (minutes, the label the foot uses for that length elsewhere).
WINDOWS = {"5h": (300, "5-hour"), "weekly": (10080, "Weekly")}
#: How agy's quota description lists a group's models.
MODELS_PREFIX = "Models within this group:"


def find_agy(paths=AGY_PATHS):
    """agy's path, or None when it is not on this Mac."""
    found = shutil.which("agy")
    if found:
        return found
    for path in paths:
        path = os.path.expanduser(path)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _window(bucket, read_at):
    window = bucket.get("window") if isinstance(bucket, dict) else None
    if not isinstance(window, str) or window not in WINDOWS:
        return None
    left = bucket.get("remaining_fraction")
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        return None
    minutes, label = WINDOWS[window]
    used = round(min(100.0, max(0.0, (1 - float(left)) * 100)), 1)
    resets_at = _epoch(bucket.get("reset_time"))
    seconds = minutes * 60
    # As an account meter's: the even-spend mark stands as of the reading, and
    # only for windows of a day or more.
    even = (pace(used, resets_at, read_at, window=seconds)
            if resets_at is not None and seconds >= DAY_SECONDS else None)
    return {"label": label, "used": used, "resets_at": resets_at, "minutes": minutes, "pace": even}


def _models(description):
    if not isinstance(description, str) or not description.startswith(MODELS_PREFIX):
        return []
    return [m.strip() for m in description[len(MODELS_PREFIX):].split(",") if m.strip()]


def quota_from_reply(text, read_at):
    """agy's JSON reply -> {"groups": [{name, models, windows}]}, or None when it holds no quota.

    Each window is {label, used, resets_at, minutes, pace}, shortest first,
    `used` the percentage spent as the account meters count it. A group with
    no window the foot can draw is left out.
    """
    try:
        reply = json.loads(text)
    except ValueError:
        return None
    if not isinstance(reply, dict) or reply.get("status") != "SUCCESS":
        return None
    command = reply.get("command")
    data = command.get("data") if isinstance(command, dict) else None
    raw_groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(raw_groups, list):
        return None
    groups = []
    for raw in raw_groups:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            continue
        buckets = raw.get("buckets") if isinstance(raw.get("buckets"), list) else []
        windows = sorted((w for w in (_window(b, read_at) for b in buckets) if w), key=lambda w: w["minutes"])
        if windows:
            groups.append({"name": raw["name"], "models": _models(raw.get("description")), "windows": windows})
    return {"groups": groups} if groups else None


def _own_folder(path):
    """`path`, made if missing, as a folder of this user's that only this user can open.

    Raises OSError when it is anything else, a link included.
    """
    os.makedirs(path, mode=0o700, exist_ok=True)
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise OSError(f"{path} is not a folder of this user")
    if stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(path, 0o700)
    return path


def run_agy(agy):
    """One `agy -p /quota` -> (exit code, stdout, stderr). Raises OSError or TimeoutExpired.

    agy starts in a new empty folder under AGY_FOLDER, taken away after the run,
    and in a session of its own, so a timeout ends whatever agy started with it.
    """
    run = tempfile.mkdtemp(prefix="run-", dir=_own_folder(AGY_FOLDER))
    try:
        proc = subprocess.Popen(
            [agy, "-p", "/quota", "--output-format", "json", "--log-file", os.devnull],
            # agy reads `true` here and ignores `1`. With its updater on, a run
            # starts a background updater that can replace the agy binary.
            cwd=run, env={**os.environ, "AGY_CLI_DISABLE_AUTO_UPDATE": "true"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", start_new_session=True)
        try:
            out, err = proc.communicate(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
            raise subprocess.TimeoutExpired(proc.args, TIMEOUT_SECONDS, output=out, stderr=err)
    finally:
        shutil.rmtree(run, ignore_errors=True)
    return proc.returncode, out, err


def _reason(out, err):
    """What agy said of a run that gave no quota: the error in its JSON reply,
    else its last line on stderr, cut to REASON_CHARS."""
    try:
        reply = json.loads(out)
    except ValueError:
        reply = None
    error = reply.get("error") if isinstance(reply, dict) and reply.get("status") == "ERROR" else None
    if isinstance(error, str) and error.strip():
        why = error.strip()
    else:
        lines = [line.strip() for line in err.splitlines() if line.strip()]
        why = lines[-1] if lines else "no message"
    return why[:REASON_CHARS]


def _figures(quota):
    """What a reading says of each window, without its times: two readings with
    the same figures hold still."""
    return [(g["name"], [(w["label"], w["used"]) for w in g["windows"]]) for g in quota["groups"]]


def _expired(window, now):
    """A window whose reset has passed since the reading reads empty until the next one."""
    if window["resets_at"] is not None and window["resets_at"] <= now:
        return {**window, "used": 0.0, "resets_at": None, "pace": None}
    return window


class Quota:
    """The last quota agy reported, and when to ask it again.

    `step` runs in a worker thread of watch_antigravity and `reload` in a
    thread of its own for each press of reload. One lock keeps two asks from
    overlapping: an ask that finds another in flight skips, and whether one
    is due is decided under the lock. Both take `on`, the Antigravity quota
    setting: while it is off, agy is never started and nothing shows.
    """

    def __init__(self, find=None, run=None, log=lambda *words: None):
        # Looked up at each ask, not bound here, so a test can stand in for them.
        self.find = find or (lambda: find_agy())
        self.run = run or (lambda agy: run_agy(agy))
        self.log = log
        # What the foot draws, replaced whole so a snapshot taken while an ask
        # ends never mixes two asks: None, or (reading, read_at, failed).
        self._shown = None
        self._said = None        # the failure last logged, until a good reading
        self.asked_at = None
        self.next_at = 0.0
        # The wait after a good reading: READ_SECONDS, doubled after each one
        # whose figures match the last, up to QUIET_READ_SECONDS.
        self.gap = READ_SECONDS
        self._lock = threading.Lock()

    @property
    def reading(self):
        """{"groups": [...]} from the last good reply, or None."""
        shown = self._shown
        return shown[0] if shown else None

    @property
    def read_at(self):
        """When that reply came, or None."""
        shown = self._shown
        return shown[1] if shown else None

    @property
    def failed(self):
        """Whether the latest ask failed after that reply."""
        shown = self._shown
        return shown[2] if shown else False

    def step(self, now, on):
        """Ask agy if a reading is due. Returns whether the snapshot may have changed."""
        if not on:
            return self._off()
        return self._ask(now, lambda: now >= self.next_at)

    def reload(self, now, on):
        """The reload button: ask now unless the last ask was moments ago, and
        every READ_SECONDS again from here."""
        if not on:
            return self._off()

        def due():
            self.gap = READ_SECONDS
            if self.asked_at is None or now - self.asked_at >= RELOAD_FLOOR_SECONDS:
                return True
            # Too soon to ask again, but the next ask is still no more than
            # READ_SECONDS after the last.
            self.next_at = min(self.next_at, self.asked_at + READ_SECONDS)
            return False
        return self._ask(now, due, stretch=False)

    def _off(self):
        # Without the lock: an ask already in flight may still show its
        # answer, and the next step clears it again.
        changed = self._shown is not None
        self._shown = None
        # Turned on again, agy is asked at once.
        self.next_at = 0.0
        self.gap = READ_SECONDS
        return changed

    def _ask(self, now, due, stretch=True):
        # An ask in flight gets the answer this one would, so this one skips
        # rather than wait and start a second agy.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if not due():
                return False
            agy = self.find()
            if agy is None:
                changed = self._shown is not None
                self._shown = None
                self.next_at = now + READ_SECONDS
                return changed
            self.asked_at = now
            # Set before agy runs, so an ask that raises still waits its interval.
            self.next_at = now + READ_SECONDS
            try:
                code, out, err = self.run(agy)
            except (OSError, UnicodeDecodeError, subprocess.SubprocessError) as error:
                return self._failed(now, f"agy did not answer: {error!r}")
            try:
                quota = quota_from_reply(out, now) if code == 0 else None
            except (ValueError, TypeError, ArithmeticError) as error:
                return self._failed(now, f"agy's reply could not be read: {error!r}")
            if quota is None:
                return self._failed(now, f"agy /quota exited {code}: {_reason(out, err)}")
            shown = self._shown
            # Figures that hold still from one reading to the next stretch the
            # gap; a change, or a reload's own reading, brings it back.
            if stretch and shown is not None and _figures(quota) == _figures(shown[0]):
                self.gap = min(self.gap * 2, QUIET_READ_SECONDS)
            else:
                self.gap = READ_SECONDS
            self._shown = (quota, now, False)
            self._said = None
            self.next_at = now + self.gap
            return True
        finally:
            self._lock.release()

    def _failed(self, now, why):
        # A run that keeps failing the same way is logged once: nothing rotates daemon.log.
        if why != self._said:
            self.log("antigravity quota not read:", why)
            self._said = why
        self.next_at = now + READ_SECONDS
        shown = self._shown
        # With no reading nothing shows, failed or not.
        if shown is None or shown[2]:
            return False
        self._shown = (shown[0], shown[1], True)
        return True

    def snapshot(self, now):
        """What the foot draws, or None with nothing to show.

        {"groups": [...]} with each window as of `now` (a passed reset reads
        0%), and "as_of", the reading's time, while the latest ask failed.
        """
        shown = self._shown
        if shown is None:
            return None
        reading, read_at, failed = shown
        groups = [{**g, "windows": [_expired(w, now) for w in g["windows"]]} for g in reading["groups"]]
        return {"groups": groups, **({"as_of": read_at} if failed else {})}
