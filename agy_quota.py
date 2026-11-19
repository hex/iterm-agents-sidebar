#!/usr/bin/env python3.10
# ABOUTME: Antigravity CLI quota for the Agents panel, read by running `agy -p /quota` now and then.
# ABOUTME: agy asks Google on its own login; the panel never reads, keeps or sends that login itself.
"""agy prints its quota as JSON in print mode, with no model turn and no tokens spent.

`agy -p /quota --output-format json` answers with the account's quota groups
(Gemini models, Claude and GPT models, a model with an allowance of its own),
each with its windows: how much of it is left and when it fully refreshes.
The same command run on a `GEMINI_API_KEY` has no account quota to show and
exits with code 2.
"""
import json
import os
import shutil
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
#: How long to leave agy alone after it says the login has no account quota (an API key).
NO_QUOTA_SECONDS = 60 * 60
#: A press of reload asks again unless the last ask is this recent.
RELOAD_FLOOR_SECONDS = 60
#: agy loads its tools and logs in before it answers; past this it is stuck.
TIMEOUT_SECONDS = 60
#: agy's exit code when the login has no account quota to show.
NO_QUOTA_EXIT = 2
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
    if not isinstance(bucket, dict) or bucket.get("window") not in WINDOWS:
        return None
    left = bucket.get("remaining_fraction")
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        return None
    minutes, label = WINDOWS[bucket["window"]]
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
    """One `agy -p /quota` -> (exit code, stdout). Raises OSError or TimeoutExpired.

    agy starts in a new empty folder under AGY_FOLDER, taken away after the run.
    """
    run = tempfile.mkdtemp(prefix="run-", dir=_own_folder(AGY_FOLDER))
    try:
        done = subprocess.run(
            [agy, "-p", "/quota", "--output-format", "json", "--log-file", os.devnull],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
            # With agy's updater asked to stay out of a run that only reads the quota.
            cwd=run, env={**os.environ, "AGY_CLI_DISABLE_AUTO_UPDATE": "1"})
    finally:
        shutil.rmtree(run, ignore_errors=True)
    return done.returncode, done.stdout


def _expired(window, now):
    """A window whose reset has passed since the reading reads empty until the next one."""
    if window["resets_at"] is not None and window["resets_at"] <= now:
        return {**window, "used": 0.0, "resets_at": None, "pace": None}
    return window


class Quota:
    """The last quota agy reported, and when to ask it again.

    `step` runs on the daemon's account loop and `reload` on the server's
    worker thread, so one lock keeps two asks from overlapping.
    """

    def __init__(self, find=None, run=None, log=lambda *words: None):
        # Looked up at each ask, not bound here, so a test can stand in for them.
        self.find = find or (lambda: find_agy())
        self.run = run or (lambda agy: run_agy(agy))
        self.log = log
        self.reading = None      # {"groups": [...]} from the last good reply
        self.read_at = None      # when that reply came
        self.failed = False      # whether the latest ask failed after it
        self.no_quota = False    # agy said the login has no account quota
        self.asked_at = None
        self.next_at = 0.0
        self._lock = threading.Lock()

    def step(self, now):
        """Ask agy if a reading is due. Returns whether the snapshot may have changed."""
        if now < self.next_at:
            return False
        return self._ask(now)

    def reload(self, now):
        """The reload button: ask now unless the last ask was moments ago."""
        if self.asked_at is not None and now - self.asked_at < RELOAD_FLOOR_SECONDS:
            return False
        return self._ask(now)

    def _ask(self, now):
        with self._lock:
            agy = self.find()
            if agy is None:
                changed = self.reading is not None or self.no_quota
                self.reading, self.read_at, self.failed, self.no_quota = None, None, False, False
                self.next_at = now + READ_SECONDS
                return changed
            self.asked_at = now
            try:
                code, out = self.run(agy)
            except (OSError, subprocess.SubprocessError) as error:
                return self._failed(now, f"agy did not answer: {error!r}")
            if code == NO_QUOTA_EXIT:
                changed = self.reading is not None or not self.no_quota
                self.reading, self.read_at, self.failed, self.no_quota = None, None, False, True
                self.next_at = now + NO_QUOTA_SECONDS
                return changed
            quota = quota_from_reply(out, now) if code == 0 else None
            if quota is None:
                return self._failed(now, f"agy /quota exited {code} without a quota")
            self.reading, self.read_at, self.failed, self.no_quota = quota, now, False, False
            self.next_at = now + READ_SECONDS
            return True

    def _failed(self, now, why):
        self.log("antigravity quota not read:", why)
        self.next_at = now + READ_SECONDS
        changed = not self.failed
        self.failed = True
        return changed

    def snapshot(self, now):
        """What the foot draws, or None with nothing to show.

        {"groups": [...]} with each window as of `now` (a passed reset reads
        0%), and "as_of", the reading's time, while the latest ask failed.
        """
        if self.reading is None:
            return None
        groups = [{**g, "windows": [_expired(w, now) for w in g["windows"]]} for g in self.reading["groups"]]
        return {"groups": groups, **({"as_of": self.read_at} if self.failed else {})}
