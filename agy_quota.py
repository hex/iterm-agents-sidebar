#!/usr/bin/env python3.10
# ABOUTME: Antigravity CLI quota for the Agents panel, read by running `agy -p /quota` now and then.
# ABOUTME: agy asks Google on its own login; the panel never reads, keeps or sends that login itself.
"""agy prints its quota as JSON in print mode, with no model turn and no tokens spent.

`agy -p /quota --output-format json` answers with the account's quota groups
(Gemini models, Claude and GPT models, a model with an allowance of its own),
each with its windows: how much of it is left and when it fully refreshes.
A run that fails, whatever its exit code, keeps the last figures with the
time they were read, for a day at most and without any window that has reset
since.
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
#: A reading this old, with every ask since failing, is dropped: nothing says what the quota holds now.
STALE_SECONDS = 24 * 60 * 60
#: A press of reload asks again unless the last ask is this recent.
RELOAD_FLOOR_SECONDS = 60
#: agy loads its tools and logs in before it answers; past this it is stuck.
TIMEOUT_SECONDS = 60
#: After a timeout's kill, how long to keep reading what agy printed before giving up on its pipes.
KILL_GRACE_SECONDS = 5
#: How much of agy's own message a log line keeps.
REASON_CHARS = 200
#: agy treats the folder it starts in as a project and reads its
#: .agents/hooks.json, so each run starts in a new empty folder under this
#: one, which the panel owns.
AGY_FOLDER = os.path.expanduser("~/.local/share/agents-sidebar/agy")
#: The `open` agy finds first on its PATH, in AGY_FOLDER/bin: it opens nothing.
OPEN_STUB = "#!/bin/sh\nexit 0\n"
#: What agy writes to stderr when it has no login and wants a browser sign-in.
SIGNED_OUT_SAYS = "Authentication required"

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


def _set_aside(bucket):
    """Why the foot cannot draw `bucket`: "unknown window" or "no remaining_fraction", else None."""
    window = bucket.get("window") if isinstance(bucket, dict) else None
    if not isinstance(window, str) or window not in WINDOWS:
        return "unknown window"
    left = bucket.get("remaining_fraction")
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        return "no remaining_fraction"
    return None


def _window(bucket, read_at):
    if _set_aside(bucket):
        return None
    window, left = bucket["window"], bucket["remaining_fraction"]
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


def quota_from_reply(text, read_at, skipped=None):
    """agy's JSON reply -> {"groups": [{name, models, windows}]}, or None when it holds no quota.

    Each window is {label, used, resets_at, minutes, pace}, shortest first,
    `used` the percentage spent as the account meters count it. A group with
    no window the foot can draw is left out. When `skipped` is a list, each
    bucket set aside adds (group name, window, reason) to it.
    """
    try:
        reply = json.loads(text)
    # RecursionError: a reply nested too deep to parse.
    except (ValueError, RecursionError):
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
        if skipped is not None:
            for bucket in buckets:
                why = _set_aside(bucket)
                if why:
                    skipped.append((raw["name"], bucket.get("window") if isinstance(bucket, dict) else None, why))
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


def _stub_open(folder):
    """`folder`/open as OPEN_STUB: kept only when it is a plain file of mode 0700
    that holds OPEN_STUB, read without following a link. Anything else there, a
    link included, is removed and the file written anew.

    Raises OSError when it cannot be, a folder in its place included.
    """
    path = os.path.join(folder, "open")
    try:
        found = os.lstat(path)
    except FileNotFoundError:
        found = None
    if found is not None:
        try:
            if stat.S_ISREG(found.st_mode) and stat.S_IMODE(found.st_mode) == 0o700:
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as stub:
                    if stub.read() == OPEN_STUB:
                        return path
        except (OSError, ValueError):
            pass
        os.unlink(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700)
    with os.fdopen(fd, "w", encoding="utf-8") as stub:
        stub.write(OPEN_STUB)
    os.chmod(path, 0o700)
    return path


def run_agy(agy):
    """One `agy -p /quota` -> (exit code, stdout, stderr). Raises OSError or TimeoutExpired.

    agy starts in a new empty folder under AGY_FOLDER, taken away after the run,
    and in a session of its own, so a timeout ends agy and whatever is still in
    that session. KILL_GRACE_SECONDS later the run stops reading what agy
    printed, so a process that left the session cannot hold it.
    """
    home = _own_folder(AGY_FOLDER)
    bin_folder = _own_folder(os.path.join(home, "bin"))
    # Signed out, agy runs `open` on a Google sign-in URL, looked up on PATH,
    # and waits a minute for the sign-in; this stub keeps the panel from ever
    # opening a browser.
    _stub_open(bin_folder)
    run = tempfile.mkdtemp(prefix="run-", dir=home)
    try:
        proc = subprocess.Popen(
            [agy, "-p", "/quota", "--output-format", "json", "--log-file", os.devnull],
            # agy reads `true` here and ignores `1`. With its updater on, a run
            # starts a background updater that can replace the agy binary.
            cwd=run, env={**os.environ, "PATH": bin_folder + os.pathsep + os.environ.get("PATH", os.defpath),
                          "AGY_CLI_DISABLE_AUTO_UPDATE": "true"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", start_new_session=True)
        try:
            out, err = proc.communicate(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            # macOS answers EPERM, not ESRCH, for a group whose members are all
            # zombies, as when agy has exited and only a process that left its
            # session is left.
            except (ProcessLookupError, PermissionError):
                pass
            try:
                out, err = proc.communicate(timeout=KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired as held:
                # A process outside agy's session still holds the pipes: keep
                # what was read so far and reap agy.
                proc.stdout.close()
                proc.stderr.close()
                proc.wait()
                out, err = (part.decode("utf-8", errors="replace") if isinstance(part, bytes) else part or ""
                            for part in (held.stdout, held.stderr))
            raise subprocess.TimeoutExpired(proc.args, TIMEOUT_SECONDS, output=out, stderr=err)
    finally:
        shutil.rmtree(run, ignore_errors=True)
    return proc.returncode, out, err


def _reason(out, err):
    """What agy said of a run that gave no quota: the error in its JSON reply,
    else its last line on stderr, cut to REASON_CHARS. `err` may be bytes or
    None, as a timeout leaves it."""
    try:
        reply = json.loads(out)
    except (ValueError, RecursionError):
        reply = None
    error = reply.get("error") if isinstance(reply, dict) and reply.get("status") == "ERROR" else None
    if isinstance(error, str) and error.strip():
        why = error.strip()
    else:
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        lines = [line.strip() for line in (err or "").splitlines() if line.strip()]
        why = lines[-1] if lines else "no message"
    return why[:REASON_CHARS]


def _says_signed_out(out, err):
    """Whether a run that gave no quota says agy has no login: SIGNED_OUT_SAYS on
    its stderr, or an authentication error in its JSON reply."""
    if isinstance(err, bytes):
        err = err.decode("utf-8", errors="replace")
    if isinstance(err, str) and SIGNED_OUT_SAYS in err:
        return True
    try:
        reply = json.loads(out) if out else None
    except (ValueError, TypeError, RecursionError):
        return False
    error = reply.get("error") if isinstance(reply, dict) and reply.get("status") == "ERROR" else None
    return isinstance(error, str) and "authentication" in error.lower()


def _figures(quota):
    """What a reading says of each window, without its times: two readings with
    the same figures hold still."""
    return [(g["name"], [(w["label"], w["used"]) for w in g["windows"]]) for g in quota["groups"]]


def _expired(window, now):
    """While readings succeed, a window whose reset has passed since the last reads empty until the next."""
    if window["resets_at"] is not None and window["resets_at"] <= now:
        return {**window, "used": 0.0, "resets_at": None, "pace": None}
    return window


class Quota:
    """The last quota agy reported, and when to ask it again.

    `step` runs in a worker thread of watch_antigravity and `reload` in a
    thread of its own for each press of reload. One lock keeps two asks from
    overlapping: an ask that finds another in flight skips, and whether one
    is due is decided under the lock. A press of reload that finds an ask in
    flight takes effect as that ask ends. Both take `on`, the Antigravity quota
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
        self._skipped_said = set()   # each bucket the foot cannot draw, logged once
        self.asked_at = None
        self.next_at = 0.0
        # The wait after a good reading: READ_SECONDS, doubled after each one
        # whose figures match the last, up to QUIET_READ_SECONDS.
        self.gap = READ_SECONDS
        # Set by a signed-out answer: no step asks again until a press of
        # reload, or the setting going off, clears it.
        self.signed_out = False
        # Set by a press of reload, and taken under the lock by the press's
        # own ask or, when it found one in flight, as that one ends.
        self._pressed = False
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
            return self.reset()
        return self._ask(now, lambda: not self.signed_out and now >= self.next_at)

    def reload(self, now, on):
        """The reload button: ask now unless the last ask was moments ago, and
        every READ_SECONDS again from here."""
        if not on:
            return self.reset()
        self._pressed = True

        def due():
            return self.asked_at is None or now - self.asked_at >= RELOAD_FLOOR_SECONDS
        return self._ask(now, due, stretch=False)

    def _take_press(self):
        # Under the lock. A press clears a signed-out pause and the stretched
        # gap, and even when it is too soon to ask again, the next ask is no
        # more than READ_SECONDS after the last.
        if not self._pressed:
            return
        self._pressed = False
        self.signed_out = False
        self.gap = READ_SECONDS
        if self.asked_at is not None:
            self.next_at = min(self.next_at, self.asked_at + READ_SECONDS)

    def reset(self):
        """Forget the reading and any pause: the setting went off, or was just
        switched. The next step with the setting on asks at once. Returns
        whether the snapshot changed."""
        # Without the lock: an ask already in flight may still show its
        # answer, and the next step clears it again.
        changed = self._shown is not None
        self._shown = None
        # Turned on again, agy is asked at once.
        self.next_at = 0.0
        self.gap = READ_SECONDS
        self.signed_out = False
        return changed

    def _ask(self, now, due, stretch=True):
        # An ask in flight gets the answer this one would, so this one skips
        # rather than wait and start a second agy.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._take_press()
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
                # The panel's timeout usually ends a signed-out agy before its
                # own wait for a sign-in does.
                if isinstance(error, subprocess.TimeoutExpired):
                    if _says_signed_out(None, error.stderr):
                        return self._pause_signed_out(now)
                    return self._failed(now, f"agy did not answer within {TIMEOUT_SECONDS} s: "
                                             f"{_reason('', error.stderr)}")
                return self._failed(now, f"agy did not answer: {error!r}")
            skipped = []
            try:
                quota = quota_from_reply(out, now, skipped) if code == 0 else None
            except (ValueError, TypeError, ArithmeticError, RecursionError) as error:
                return self._failed(now, f"agy's reply could not be read: {error!r}")
            # Google names the windows, so one the panel does not know can
            # come without an agy update.
            for group, window, reason in skipped:
                line = f"antigravity quota: {group} window {window!r} not drawn ({reason})"
                if line not in self._skipped_said:
                    self.log(line)
                    self._skipped_said.add(line)
            if quota is None:
                if _says_signed_out(out, err):
                    return self._pause_signed_out(now)
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
            # A press that came while agy was asked counts after its answer.
            self._take_press()
            self._lock.release()

    def _pause_signed_out(self, now):
        # Asked again, agy would only wait another minute for a sign-in.
        self.signed_out = True
        return self._failed(now, "agy is signed out; asking again after a press of reload")

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
        While asks fail, a window whose reset has passed is left out, a group
        left with none goes, and a reading STALE_SECONDS old shows nothing.
        """
        shown = self._shown
        if shown is None:
            return None
        reading, read_at, failed = shown
        if not failed:
            return {"groups": [{**g, "windows": [_expired(w, now) for w in g["windows"]]} for g in reading["groups"]]}
        if now - read_at >= STALE_SECONDS:
            return None
        groups = [{**g, "windows": [w for w in g["windows"] if w["resets_at"] is None or w["resets_at"] > now]}
                  for g in reading["groups"]]
        groups = [g for g in groups if g["windows"]]
        return {"groups": groups, "as_of": read_at} if groups else None
