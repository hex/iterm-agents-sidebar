# ABOUTME: Running Claude sessions on API credits while every subscription account is full: the
# ABOUTME: persisted record, the pure step that moves it, the Keychain key and its validation call.
"""The fallback's whole state is one record, and `step` is the only thing that
moves it: given the record, a reading of the accounts and settings, and the
clock, it returns the next record and the effects the daemon carries out.

Phases: off -> entering (a notice with Not now, for NOTICE_GRACE_SECONDS) ->
on (apiKeyHelper in settings.json) -> leaving (a notice with Not now) -> off.
A hold keeps an off record from entering again until an account has room.
"""
import json
import os
import re
import socket
import urllib.error
import urllib.request
from typing import NamedTuple

import accounts

NOTICE_GRACE_SECONDS = 60
EXIT_ASK_AGAIN_SECONDS = 1800

PHASES = ("off", "entering", "on", "leaving")
HOLD_REASONS = ("not_now", "cap", "billing_error", "authentication_failed", "refused", "helper_gone", "no_bridge")
#: The StopFailure errors that end the key in use at once.
FAILURE_EXITS = ("billing_error", "authentication_failed")
#: Why one account's key is skipped until the blocked state ends.
KEY_HOLD_REASONS = ("cap", "billing_error", "authentication_failed", "refused")
#: The holds of a fallback that ended for want of a key, lifted once a key is usable again.
KEY_EXITS = ("cap", "billing_error", "authentication_failed")


def blank():
    """The record of an install that never entered: off, no hold."""
    return {"phase": "off", "deadline": None, "since": None, "ask_again_at": None, "hold": None,
            "last_cost": {}, "spend": {}, "flips": 0, "last_flip": None, "command": None,
            "writing": False, "retrying": None, "key_account": None, "key_holds": {}}


def _hold(reason, why, now):
    return {"reason": reason, "at": now, "why": why}


#: The words each exit with a hold is shown and logged with.
EXIT_WHY = {"cap": "cap reached", "billing_error": "API credits ran out",
            "authentication_failed": "the API key was refused",
            "no_bridge": "the spend cap needs the statusline bridge, which is not installed",
            "helper_gone": "apiKeyHelper was taken out of settings.json by something else"}


def key_order(reading):
    """The accounts whose key the fallback may use, in the order it tries them:
    the active account's, then the others' in the accounts' list order."""
    keyed = [account["id"] for account in reading["accounts"] if account["key"]]
    active = reading["active"]
    return ([active] if active in keyed else []) + [account_id for account_id in keyed if account_id != active]


def usable_keys(record, reading):
    """key_order without the keys held for this blocked state."""
    return [account_id for account_id in key_order(reading) if account_id not in record["key_holds"]]


def _account(reading, account_id):
    return next((account for account in reading["accounts"] if account["id"] == account_id), None)


def _taken_back(record):
    """Off, as if the entry had never happened: a record moved to on whose helper
    never reached the sessions gives its flip back."""
    entered = record["phase"] == "on"
    return dict(record, phase="off", deadline=None, since=None, ask_again_at=None, writing=False,
                flips=record["flips"] - 1 if entered else record["flips"],
                last_flip=None if entered else record["last_flip"])


def _no_bridge(record, now):
    """-> (record, effects): off, held until the bridge is back or an account has
    room, because the spend cap reads each session's cost from the bridge."""
    why = EXIT_WHY["no_bridge"]
    return (dict(_taken_back(record), hold=_hold("no_bridge", why, now), retrying=None),
            [{"do": "notice", "which": "refused", "why": why}, {"do": "log", "line": f"api fallback refused: {why}"}])


def refused(record, why, now):
    """Off with a `refused` hold: the entry could not go ahead."""
    return dict(_taken_back(record), hold=_hold("refused", why, now), retrying=None)


def _retry_said(record, why):
    """The notice and log line for a key that could not be checked: said for the
    first failure of a blocked episode only."""
    return [] if record["retrying"] else [
        {"do": "notice", "which": "unavailable", "why": why},
        {"do": "log", "line": f"api fallback could not check the key: {why}; trying again while the accounts stay full"}]


def unavailable(record, why):
    """Off with no hold, as an API that could not say whether the key is good is
    no verdict on the key: -> (record, effects). `retrying` keeps the reason for
    the rest of the blocked episode, so the next ticks try again without a notice
    or a grace, and only the first failure is said or logged."""
    return dict(_taken_back(record), retrying=record["retrying"] or why), _retry_said(record, why)


def failures_on_key(failures, fetches, key_account):
    """The errors of `failures` that are the key in use's: each from a session
    whose last fetch at or before the failure took `key_account`. `failures` are
    {error, pid, at}; `fetches` maps a Claude Code pid to its (at, account)
    fetches in order. A session that took no key yet ran on the subscription, and
    one still on an earlier key failed on that key, which was held when the
    fallback moved off it."""
    blamed = []
    for failure in failures:
        taken = [account for at, account in fetches.get(failure["pid"], []) if at <= failure["at"]]
        if taken and taken[-1] == key_account:
            blamed.append(failure["error"])
    return blamed


def _due(record, reading):
    """Whether entry is wanted: the setting on, a key that may be used, and every
    account (or every running model) full. An unreadable account is not a full one."""
    return (reading["enabled"] and reading["blocked"] in ("full", "model_full")
            and bool(usable_keys(record, reading)))


#: Why a helper state stops an entry; a state not here can be written over.
HELPER_REFUSALS = {"foreign": "another tool's apiKeyHelper is set in settings.json",
                   "unreadable": "settings.json cannot be read"}


def spent(record):
    """Dollars this fallback has cost, on every key it used."""
    return sum(record["spend"].values())


def key_saved(record, account_id):
    """A key was stored for `account_id`: a verdict on the key it replaces no
    longer holds it, and an entry it or any other key's refusal stopped may come
    again. A cap stays: it is the account's spend, whatever key it uses."""
    hold = record["hold"]
    holds = {held: why for held, why in record["key_holds"].items()
             if held != account_id or why["reason"] == "cap"}
    return dict(record, key_holds=holds, hold=None if hold and hold["reason"] == "refused" else hold)


def _key_holds_lifted(record, reading):
    """Every key hold ends once an account has room, and a key's cap hold once its
    cap stands above what this fallback has spent on it."""
    holds = record["key_holds"]
    if not holds:
        return record
    if reading["room"]:
        kept = {}
    else:
        caps = {account["id"]: account["cap_usd"] for account in reading["accounts"]}
        kept = {account_id: hold for account_id, hold in holds.items()
                if not (hold["reason"] == "cap" and account_id in caps
                        and caps[account_id] > record["spend"].get(account_id, 0))}
    return record if kept == holds else dict(record, key_holds=kept)


def _lifted(record, reading):
    """Whether an off record's hold ends: any hold once an account has room, one
    that ended the last key once a key is usable again, and the bridge's when the
    bridge is back."""
    reason = record["hold"]["reason"]
    return (reading["room"] or (reason in KEY_EXITS and bool(usable_keys(record, reading)))
            or (reason == "no_bridge" and reading["bridge"]))


def _step_off(record, reading, now):
    if record["hold"]:
        return (dict(record, hold=None) if _lifted(record, reading) else record), []
    if not _due(record, reading):
        return (dict(record, retrying=None) if record["retrying"] else record), []
    why = HELPER_REFUSALS.get(reading["helper"])
    if why:
        return refused(record, why, now), [{"do": "notice", "which": "refused", "why": why},
                                           {"do": "log", "line": f"api fallback refused: {why}"}]
    if not reading["bridge"]:
        return _no_bridge(record, now)
    if record["retrying"]:
        return _entered(record, reading, now), [{"do": "helper_in"}]
    return (dict(record, phase="entering", deadline=now + NOTICE_GRACE_SECONDS),
            [{"do": "notice", "which": "entry", "tokens": reading["reread_tokens"]}])


def _step_entering(record, reading, now):
    if reading["answer"] == "not_now":
        return (dict(record, phase="off", deadline=None, hold=_hold("not_now", "Not now, until an account has room", now)),
                [{"do": "notice_down"}])
    if not _due(record, reading) or reading["helper"] in HELPER_REFUSALS:
        return dict(record, phase="off", deadline=None), [{"do": "notice_down"}]
    if not reading["bridge"]:
        record, effects = _no_bridge(record, now)
        return record, [{"do": "notice_down"}] + effects
    if now < record["deadline"]:
        return record, []
    return (_entered(record, reading, now),
            [{"do": "notice_down"}, {"do": "helper_in"}, {"do": "log", "line": "api fallback on: sessions move to API credits"}])


def _using(record, account):
    """The record with `account`'s key in use: its command is the one to write, and the mark says a write is due."""
    return dict(record, key_account=account["id"], command=account["command"], writing=True)


def _entered(record, reading, now):
    """On with the first usable key, its write to come: the spend starts here."""
    why = "every account is full" if reading["blocked"] == "full" else "the running models are full on every account"
    first = _account(reading, usable_keys(record, reading)[0])
    return _using(dict(record, phase="on", deadline=None, since=now, ask_again_at=None, last_cost=dict(reading["costs"]),
                       spend={}, flips=record["flips"] + 1, last_flip={"at": now, "to": "api", "why": why}), first)


def _tallied(record, costs):
    """Add each session's rise since its last figure to the spend on the key in
    use. A figure lower than the last is a new process counting from 0, so it adds
    itself; a session first seen now also counts from 0; only entry sets a figure
    without adding to the spend."""
    last_cost, rise = dict(record["last_cost"]), 0
    for session, cost in costs.items():
        before = last_cost.get(session, 0)
        rise += cost - before if cost >= before else cost
        last_cost[session] = cost
    key = record["key_account"]
    return dict(record, last_cost=last_cost, spend=dict(record["spend"], **{key: record["spend"].get(key, 0) + rise}))


def _ended(record, reason, now, why=None):
    """Off, back on the subscription: held for `reason`, or not when it is None."""
    why = why or EXIT_WHY[reason]
    return dict(record, phase="off", deadline=None, since=None, ask_again_at=None, flips=record["flips"] + 1,
                writing=False, hold=_hold(reason, why, now) if reason else None,
                last_flip={"at": now, "to": "subscription", "why": why})


def orphaned(record, now):
    """The helper took itself out, the daemon being down or the key unreadable:
    the sessions are back on the subscription already, by no other tool's
    doing, so nothing holds."""
    return _ended(record, None, now, "the helper took itself out")


def _moved(record, reading, why, ended):
    """-> (record, effects): the next usable key takes over at once, its write and
    check to come and its notice after them; with none left, `ended`."""
    following = usable_keys(record, reading)
    if not following:
        return ended
    return _using(record, _account(reading, following[0])), [{"do": "helper_in", "moved": why}]


def _key_ended(record, reading, reason, now, why=None):
    """The key in use is done for `reason`: held, and the next usable key takes
    over, or with none left the fallback ends and holds for that reason."""
    why = why or EXIT_WHY[reason]
    held = dict(record, key_holds=dict(record["key_holds"], **{record["key_account"]: _hold(reason, why, now)}))
    key_spend = record["spend"].get(record["key_account"], 0)
    ended = (_ended(held, reason, now, why), [
        {"do": "helper_out"}, {"do": "notice", "which": reason, "why": why},
        {"do": "log", "line": f"api fallback off: {why} (${key_spend:.2f} on {record['key_account']}'s key)"}])
    return _moved(held, reading, why, ended)


def _ends_at_once(record, reading, now):
    """While the helper is in: (record, effects) for whatever ends the fallback or
    the key in use without a grace, checked in order, or None. A helper that is no
    longer ours is never written; a setting turned off, or the key in use
    forgotten, is a choice and holds nothing; a failed turn outranks the cap, whose
    figure it may have stopped; a bridge that went away leaves as the cap would,
    because no cap can be read without it."""
    if reading["helper"] in ("absent", "foreign"):
        return _ended(record, "helper_gone", now), [
            {"do": "log", "line": f"api fallback off: {EXIT_WHY['helper_gone']}; not written back"}]
    if not reading["enabled"]:
        why = "the setting was turned off"
        return _ended(record, None, now, why), [{"do": "helper_out"}, {"do": "log", "line": f"api fallback off: {why}"}]
    account = _account(reading, record["key_account"])
    if account is None or not account["key"]:
        why = "the key was forgotten"
        return _moved(record, reading, why, (_ended(record, None, now, why), [
            {"do": "helper_out"}, {"do": "log", "line": f"api fallback off: {why}"}]))
    failures = [error for error in FAILURE_EXITS if error in reading["stop_failures"]]
    if failures:
        return _key_ended(record, reading, failures[0], now)
    if not reading["bridge"]:
        return _ended(record, "no_bridge", now), [
            {"do": "helper_out"}, {"do": "notice", "which": "no_bridge", "why": EXIT_WHY["no_bridge"]},
            {"do": "log", "line": f"api fallback off: {EXIT_WHY['no_bridge']} (${spent(record):.2f})"}]
    if record["spend"].get(account["id"], 0) > account["cap_usd"]:
        return _key_ended(record, reading, "cap", now)
    return None


def _step_on(record, reading, now):
    if reading["helper"] == "unreadable":
        return record, []
    if record["writing"]:
        if reading["helper"] == "absent":
            return _taken_back(record), [{"do": "log", "line": "api fallback off: the daemon stopped while writing apiKeyHelper"}]
        if reading["helper"] == "ours" and reading["helper_command"] != record["command"]:
            # A daemon that stopped between a move's save and its write left the old key's command.
            return record, [{"do": "helper_in"}]
        record = dict(record, writing=False)
    record = _tallied(record, reading["costs"])
    ended = _ends_at_once(record, reading, now)
    if ended:
        return ended
    if reading["room"] and now >= (record["ask_again_at"] or 0):
        return (dict(record, phase="leaving", deadline=now + NOTICE_GRACE_SECONDS, ask_again_at=None),
                [{"do": "notice", "which": "exit", "tokens": reading["reread_tokens"]}])
    return record, []


def _step_leaving(record, reading, now):
    if reading["helper"] == "unreadable":
        return record, []
    record = _tallied(record, reading["costs"])
    down = [{"do": "notice_down"}]
    ended = _ends_at_once(record, reading, now)
    if ended:
        # A move to another key leaves the way out pending; only an end takes its notice down.
        return ended if ended[0]["phase"] == "leaving" else (ended[0], down + ended[1])
    if reading["answer"] == "not_now":
        return dict(record, phase="on", deadline=None, ask_again_at=now + EXIT_ASK_AGAIN_SECONDS), down
    if not reading["room"]:
        return dict(record, phase="on", deadline=None), down
    if now < record["deadline"]:
        return record, []
    return _ended(record, None, now, "an account has room"), down + [
        {"do": "helper_out"}, {"do": "log", "line": "api fallback off: sessions go back to the subscription"}]


#: Phase -> the function that steps a record in it.
STEPS = {"off": _step_off, "entering": _step_entering, "on": _step_on, "leaving": _step_leaving}
#: The phases in which apiKeyHelper belongs in settings.json.
HELPER_IN = ("on", "leaving")


def owned_commands(record, own_commands):
    """The apiKeyHelper commands that are the panel's: exactly the one the record
    says was last written, and this checkout's own for each stored account.
    Nothing else is ever touched."""
    return {command for command in (record["command"], *own_commands) if command}


def checked(record, reading, effect, problem, now):
    """-> (record, effects) once a `helper_in` effect has run: the key in use was
    checked against the API and its command written, or `problem` says why not.

    `reading` is the one the step that asked for the write saw: a helper of ours
    in it means sessions already run on a key, so a failure here ends a fallback
    rather than an entry. A key the API refused is held and the next usable key
    is tried; an API that gave no verdict, or a problem on this machine, stops
    there.
    """
    running = reading["helper"] == "ours"
    if problem is None:
        done = dict(record, writing=False, retrying=None)
        if effect.get("moved"):
            name = _account(reading, record["key_account"])["name"]
            return done, [{"do": "notice", "which": "moved", "why": effect["moved"], "name": name},
                          {"do": "log", "line": f"api fallback: {effect['moved']}; sessions now use {name}'s key"}]
        if record["retrying"]:
            return done, [{"do": "log", "line": "api fallback on: the API answered, sessions move to API credits"}]
        return done, []
    if problem.kind == "unavailable":
        if not running:
            return unavailable(record, problem.why)
        return (dict(_ended(record, None, now, problem.why), retrying=record["retrying"] or problem.why),
                [{"do": "helper_out"}] + _retry_said(record, problem.why))
    if problem.kind == "local":
        if not running:
            return refused(record, problem.why, now), [{"do": "notice", "which": "refused", "why": problem.why},
                                                       {"do": "log", "line": f"api fallback refused: {problem.why}"}]
        return _ended(record, "refused", now, problem.why), [
            {"do": "helper_out"}, {"do": "notice", "which": "refused", "why": problem.why},
            {"do": "log", "line": f"api fallback off: {problem.why}"}]
    held = dict(record, key_holds=dict(record["key_holds"], **{record["key_account"]: _hold("refused", problem.why, now)}))
    if running:
        ended = (_ended(held, "refused", now, problem.why), [
            {"do": "helper_out"}, {"do": "notice", "which": "refused", "why": problem.why},
            {"do": "log", "line": f"api fallback off: {problem.why}"}])
    else:
        ended = (refused(held, problem.why, now), [{"do": "notice", "which": "refused", "why": problem.why},
                                                    {"do": "log", "line": f"api fallback refused: {problem.why}"}])
    return _moved(held, reading, problem.why, ended)


def step(record, reading, now):
    """-> (the next record, the effects to carry out in order).

    An install that never turned the setting on and never entered is left
    entirely alone. Otherwise a panel-owned helper found while the record says
    it should not be in (a daemon that stopped between writing it and saving
    the record) comes out first, whatever the phase goes on to do.
    """
    if not reading["enabled"] and record == blank():
        return record, []
    stray = [] if record["phase"] in HELPER_IN or reading["helper"] != "ours" else [
        {"do": "helper_out"}, {"do": "log", "line": "api fallback: took out a helper the record does not hold"}]
    record, effects = STEPS[record["phase"]](_key_holds_lifted(record, reading), reading, now)
    return record, stray + effects


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_hold(hold, reasons):
    return (isinstance(hold, dict) and hold.get("reason") in reasons
            and _number(hold.get("at")) and isinstance(hold.get("why"), str))


def _parse(doc):
    """A stored record, checked field by field; ValueError naming the first bad one."""
    if not isinstance(doc, dict):
        raise ValueError("not a JSON object")
    record = blank()
    record.update({key: doc[key] for key in record if key in doc})
    if record["phase"] not in PHASES:
        raise ValueError(f"phase {record['phase']!r}")
    for key in ("deadline", "since", "ask_again_at"):
        if record[key] is not None and not _number(record[key]):
            raise ValueError(f"{key} {record[key]!r}")
    if record["hold"] is not None and not _is_hold(record["hold"], HOLD_REASONS):
        raise ValueError(f"hold {record['hold']!r}")
    for key, keyed_by in (("last_cost", "session ids"), ("spend", "account ids")):
        if not (isinstance(record[key], dict) and all(isinstance(k, str) and _number(v) for k, v in record[key].items())):
            raise ValueError(f"{key} is not {keyed_by} to dollars")
    if not (isinstance(record["flips"], int) and not isinstance(record["flips"], bool)):
        raise ValueError(f"flips {record['flips']!r}")
    if record["key_account"] is not None and not isinstance(record["key_account"], str):
        raise ValueError("key_account is not text")
    holds = record["key_holds"]
    if not (isinstance(holds, dict) and all(isinstance(k, str) and _is_hold(v, KEY_HOLD_REASONS) for k, v in holds.items())):
        raise ValueError(f"key_holds {holds!r}")
    flip = record["last_flip"]
    if flip is not None and not (isinstance(flip, dict) and _number(flip.get("at"))
                                 and flip.get("to") in ("api", "subscription") and isinstance(flip.get("why"), str)):
        raise ValueError(f"last_flip {flip!r}")
    if record["command"] is not None and not isinstance(record["command"], str):
        raise ValueError("command is not text")
    if not isinstance(record["writing"], bool):
        raise ValueError(f"writing {record['writing']!r}")
    if record["retrying"] is not None and not isinstance(record["retrying"], str):
        raise ValueError("retrying is not text")
    if record["phase"] in ("entering", "leaving") and not _number(record["deadline"]):
        raise ValueError(f"{record['phase']} with no deadline")
    if record["phase"] in HELPER_IN and not accounts.is_account_id(record["key_account"]):
        raise ValueError(f"{record['phase']} with no key in use")
    return record


def load(path):
    """-> (record, problem): the stored record, or a blank one with None when
    there is none, or a blank one with the reason it could not be read."""
    try:
        text = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return blank(), None
    except OSError as error:
        return blank(), f"{path} could not be read ({error}); starting off"
    try:
        return _parse(json.loads(text)), None
    except ValueError as error:
        return blank(), f"{path} is not a fallback record ({error}); starting off"


def save(path, record):
    """Replace the record whole, private to the user, so a reader never sees half of it."""
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    staged = f"{path}.{os.getpid()}.tmp"
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    os.replace(staged, path)


#: Each account's key lives in the Keychain beside its login, as `api-key:<account id>`,
#: and nowhere else; the store keeps its last four characters and its cap.
KEY_SERVICE = accounts.PANEL_SERVICE
KEY_ITEM_PREFIX = "api-key:"
#: What an Anthropic API key looks like: checked before it is stored or sent.
KEY_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")
NOT_A_KEY = "not an Anthropic API key"
MODELS_URL = "https://api.anthropic.com/v1/models"
API_VERSION = "2023-06-01"
VALIDATE_TIMEOUT_SECONDS = 10


def _shaped(key):
    return isinstance(key, str) and KEY_SHAPE.fullmatch(key) is not None


def key_item(account_id):
    """The Keychain account that holds `account_id`'s key. Raises ValueError for
    an id not in the store's format, so no other item can be named this way."""
    if not accounts.is_account_id(account_id):
        raise ValueError(f"{account_id!r} is not an account id")
    return KEY_ITEM_PREFIX + account_id


def store_key(store_path, account_id, key):
    """Keep `key` for a stored account: in the Keychain over stdin, then its last
    four characters in the store, all the page ever sees. -> those four. Raises
    ValueError for text that is not a key or an account that is not stored."""
    if not _shaped(key):
        raise ValueError(NOT_A_KEY)
    item = key_item(account_id)
    accounts.stored_account(store_path, account_id)
    accounts.write_secret(KEY_SERVICE, item, key)
    accounts.edit_account(store_path, account_id, lambda account: dict(account, apiKeyLast4=key[-4:]))
    return key[-4:]


def read_key(account_id):
    """`account_id`'s stored key, or None."""
    return accounts.read_secret(KEY_SERVICE, key_item(account_id))


def forget_key(store_path, account_id):
    """Delete a stored account's key, then its last four; none stored is fine. The
    Keychain goes first: a store that still names a key it has lost refuses the
    key when the fallback asks for it, where the other order would strand it."""
    item = key_item(account_id)
    accounts.stored_account(store_path, account_id)
    accounts.delete_secret(KEY_SERVICE, item)
    accounts.edit_account(store_path, account_id,
                          lambda account: {k: v for k, v in account.items() if k != "apiKeyLast4"})


def set_cap(store_path, account_id, dollars):
    """Set the spend cap on a stored account's key. Raises ValueError for anything
    but a positive number of dollars, or an account that is not stored."""
    if not accounts.is_positive_dollars(dollars):
        raise ValueError(f"a cap is a positive number of dollars, not {dollars!r}")
    accounts.edit_account(store_path, account_id, lambda account: dict(account, apiKeyCapUsd=float(dollars)))


class KeyProblem(NamedTuple):
    """Why a key cannot be used: `refused` when the API said no (a 401 or 403) or it
    is no key at all, `unavailable` when the API gave no verdict on it, and
    `local` when this machine stopped it: the Keychain could not be read, or
    settings.json would not take the helper's command. Only `refused` holds the key."""
    kind: str
    why: str


def validate_key(key, url=MODELS_URL, timeout=VALIDATE_TIMEOUT_SECONDS):
    """One GET of the models list with `key`. -> None when the API answers for
    it, else a KeyProblem, in words that never include the key."""
    if not _shaped(key):
        return KeyProblem("refused", NOT_A_KEY)
    request = urllib.request.Request(url, headers={"x-api-key": key, "anthropic-version": API_VERSION,
                                                   "User-Agent": "agents-sidebar"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=accounts._tls()):
            return None
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return KeyProblem("refused", f"the key was refused ({error.code})")
        return KeyProblem("unavailable", f"the API answered {error.code}")
    except (socket.timeout, TimeoutError):
        return KeyProblem("unavailable", "the API did not answer (timed out)")
    except urllib.error.URLError as error:
        if isinstance(error.reason, (socket.timeout, TimeoutError)):
            return KeyProblem("unavailable", "the API did not answer (timed out)")
        return KeyProblem("unavailable", f"the API could not be reached ({error.reason})")
    except OSError as error:
        return KeyProblem("unavailable", f"the API could not be reached ({error})")
