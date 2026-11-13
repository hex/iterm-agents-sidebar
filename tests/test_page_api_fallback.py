# ABOUTME: Runs the panel's API fallback pieces under Node with the page's function harness: the
# ABOUTME: Accounts head's chip, the switch line's flip, and the Accounts card in Settings.
"""Ways this can go wrong, and the test for each:
- a pending flip shows no countdown or no Not now, so the choice needs macOS notices;
- sessions on credits show no spend, or nothing says what is off meanwhile;
- a hold or refusal reads like the ordinary state;
- an install that never turned it on gets a chip;
- the switch can be turned on with no key on any account;
- a key comes back into the page, or a refusal to save it is silent;
- a key, a Forget or a cap reaches the daemon without the account it belongs to;
- the chip does not say whose key the sessions run on;
- a row loses what is typed in it when a frame repaints the card;
- nothing under the switch says it writes ~/.claude/settings.json;
- a key's state rests on the lamp's icon and colour alone, with no word;
- the table has no header naming its columns;
- one click on Forget deletes a key, or an armed Forget stays armed;
- a cap of 0 is sent, or refused without a word for a screen reader;
- a pasted key waits for a click;
- a focus stop does not say which account it acts on;
- a frame that lands while a row shows a message gives the row more or fewer cells than the header.
"""
import json
import re
import subprocess
from pathlib import Path

from page_source import function

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text()
DOM = """
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = {}; this.dataset = {};
    this.textContent = ''; this.className = ''; this.id = ''; this.title = ''; this.disabled = false; this.hidden = false;
    this.value = ''; this.type = '';
    const node = this;
    this.classList = {add: (...c) => { node.className = [...node.className.split(' '), ...c].filter(Boolean).join(' '); },
                      contains: c => node.className.split(' ').includes(c),
                      toggle: (c, on) => { const has = node.className.split(' ').includes(c);
                        if (on === undefined ? !has : on) { if (!has) node.classList.add(c); }
                        else node.className = node.className.split(' ').filter(x => x !== c).join(' '); }}; }
  append(...nodes) { this.children.push(...nodes.map(n => typeof n === 'string' ? Object.assign(new Node('#text'), {textContent: n}) : n)); }
  replaceWith() {}
  prepend(...nodes) { this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name]; }
  removeAttribute(name) { delete this.attrs[name]; }
  hasAttribute(name) { return name in this.attrs; }
  addEventListener(name, fn) { this.events[name] = fn; }
  focus() {}
  blur() {}
  get firstChild() { return this.children[0]; }
  get lastChild() { return this.children[this.children.length - 1]; }
}
const later = setTimeout;
setTimeout = (fn, ms, ...args) => { const timer = later(fn, ms, ...args); if (ms >= 1000) timer.unref(); return timer; };
const document = {createElement: tag => new Node(tag), createTextNode: text => Object.assign(new Node('#text'), {textContent: text}),
                  getElementById: () => null};
const on = (node, name, fn) => node.addEventListener(name, fn);
const metaIcon = kind => Object.assign(new Node('svg'), {className: 'mi', dataset: {icon: kind}});
const clock = at => 'at ' + at;
const reportAge = at => 'age ' + at;
const TOKEN = 'test token';
let SETTINGS = {api_fallback: true, auto_switch: false};
let LATEST = {groups: []};
let SETTING_SYNC = [];
const pushed = [], posted = [];
function push(change) { pushed.push(change); SETTINGS = {...SETTINGS, ...change}; }
let reply = {ok: true};
function fetch(url, init) { posted.push([url, JSON.parse(init.body)]);
  return Promise.resolve({json: () => Promise.resolve(reply)}); }
function settingCard(title) { const card = new Node('div'); card.className = 'set-card';
  const head = new Node('div'); head.className = 'set-title'; head.append(title); card.append(head); return card; }
const texts = node => [node.tag === 'input' ? '' : node.textContent, ...node.children.flatMap(texts)].filter(Boolean);
const all = node => [node, ...node.children.flatMap(all)];
const tagged = (node, tag) => all(node).filter(n => n.tag === tag);
const named = (node, text) => tagged(node, 'button').find(n => n.textContent === text);
const visible = node => node.hidden || node.className.split(' ').includes('offscreen') ? []
  : [node.tag === 'input' ? '' : node.textContent, ...node.children.flatMap(visible)].filter(Boolean);
const columns = row => row.children.filter(td => !td.hidden).reduce((n, td) => n + (td.colSpan || 1), 0);
const labelled = (node, start) => all(node).find(n => n.attrs['aria-label']?.startsWith(start));
"""
NAMES = ("fallbackChip", "fallbackCountdown", "fallbackNotNow", "fallbackHoldWord", "flipLine", "movesLine", "switchLine", "apiFallbackCard",
         "apiKeyRow", "paintApiFallback", "paintApiKeyRow", "fallbackPost", "stopFailureLine", "statusLine",
         "makeEl", "apiKeyState", "apiKeySpent", "apiKeyCap")
NOW = 1_000_000


def run(body):
    script = "\n".join([DOM, *(function(PAGE, name) for name in NAMES), body])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


def chip(fallback):
    return run(f"""
const chip = fallbackChip({json.dumps(fallback)}, {NOW});
console.log(JSON.stringify(chip && {{texts: texts(chip), title: chip.title, cls: chip.className,
  buttons: tagged(chip, 'button').map(b => b.textContent)}}));
""")


def key(account_id, name, last4=None, cap_usd=50.0, spent_usd=0, hold=None):
    return {"id": account_id, "name": name, "last4": last4, "cap_usd": cap_usd, "spent_usd": spent_usd, "hold": hold}


#: alice and bob with a key each, and Account 3 without one.
KEYS = [key("acct-1", "alice", "wxyz"), key("acct-2", "bob", "abcd", cap_usd=20.0), key("acct-3", "Account 3")]
BASE = {"enabled": True, "phase": "off", "deadline": None, "since": None, "spent_usd": 0, "hold": None,
        "key_account": None, "key_name": None, "keys": KEYS, "reread_tokens": 42000, "last_flip": None}


def test_a_pending_entry_counts_down_and_offers_not_now():
    shown = chip(dict(BASE, phase="entering", deadline=NOW + 42))
    assert shown["texts"] == ["→ API in 42 s", "Not now"]
    assert shown["buttons"] == ["Not now"]
    assert "re-read about 42k tokens" in shown["title"]


def test_a_pending_exit_counts_down_to_the_subscription():
    shown = chip(dict(BASE, phase="leaving", deadline=NOW + 9))
    assert shown["texts"] == ["→ subscription in 9 s", "Not now"]


def test_on_credits_names_whose_key_shows_the_spend_and_says_what_is_off():
    keys = [KEYS[0], dict(KEYS[1], spent_usd=1.5), KEYS[2]]
    shown = chip(dict(BASE, phase="on", since=NOW - 600, spent_usd=1.84, key_account="acct-2", key_name="bob", keys=keys))
    assert shown["texts"] == ["on API · bob · $1.84"]
    assert "claude.ai connectors and Remote Control" in shown["title"]
    assert "bob's key" in shown["title"] and "$1.50 of its $20 cap" in shown["title"]
    assert "estimate" in shown["title"]
    assert "held" not in shown["cls"].split()


def test_a_hold_shows_in_the_alert_colour_with_its_reason():
    stay = "sessions stay on the subscription until an account has room"
    for reason, why, text, lifted in (
            ("cap", "cap reached", "API · cap reached", " or a key is usable again"),
            ("refused", "the key was refused (401)", "API · refused", " or a key is saved"),
            ("billing_error", "API credits ran out", "API · credits ran out", " or a key is usable again"),
            ("no_bridge", "the spend cap needs the statusline bridge", "API · needs the bridge",
             " or the bridge is installed"),
            ("helper_gone", "apiKeyHelper was taken out", "API · helper removed", "")):
        shown = chip(dict(BASE, hold={"reason": reason, "at": NOW, "why": why}))
        assert shown["texts"] == [text], reason
        assert "held" in shown["cls"].split(), reason
        assert shown["title"] == f"{why}; {stay}{lifted}", reason


def test_a_key_the_api_could_not_check_shows_it_is_trying_again():
    shown = chip(dict(BASE, retrying="the API answered 503"))
    assert shown["texts"] == ["API \u00b7 trying again"]
    assert "held" in shown["cls"].split()
    assert "the API answered 503" in shown["title"]


def test_nothing_shows_at_rest_or_for_an_install_that_never_turned_it_on():
    assert chip(None) is None
    assert chip(BASE) is None
    assert chip(dict(BASE, enabled=False, hold={"reason": "cap", "at": NOW, "why": "cap reached"})) is None


def test_not_now_asks_the_daemon():
    assert run(f"""
const chip = fallbackChip({json.dumps(dict(BASE, phase="entering", deadline=NOW + 42))}, {NOW});
named(chip, 'Not now').events.click();
console.log(JSON.stringify(posted));
""") == [["/api-fallback?token=test%20token", {"op": "not_now"}]]


def test_the_switch_line_records_each_flip():
    assert run("""
const there = flipLine({at: 5, to: 'api', why: 'every account is full'});
const back = flipLine({at: 9, to: 'subscription', why: 'cap reached'});
console.log(JSON.stringify([texts(there), texts(back)]));
""") == [["On API credits", "every account is full", "age 5"], ["Back on the subscription", "cap reached", "age 9"]]


def test_a_move_back_to_the_subscription_gives_the_line_back_to_the_last_switch_after_an_hour():
    hour = 3600
    switch = {"at": NOW - 3 * 86400, "to": "bob", "why": "alice is full", "auto": True}
    back = {"at": NOW - 2 * 86400, "to": "subscription", "why": "API credits ran out"}
    page_const = re.search(r"\nconst FLIP_LINE_SECONDS = .*;\n", PAGE).group(0)
    shown = run(page_const + f"""
let localSwitch = null;
const line = (last, flip, now) => {{ const l = movesLine(last, flip, now); return l && texts(l)[0]; }};
console.log(JSON.stringify([
  line({json.dumps(switch)}, {json.dumps(dict(back, at=NOW - hour + 60))}, {NOW}),
  line({json.dumps(switch)}, {json.dumps(back)}, {NOW}),
  line(null, {json.dumps(back)}, {NOW}),
  line({json.dumps(switch)}, {json.dumps(dict(back, to="api", why="every account is full"))}, {NOW}),
]));
""")
    assert shown == ["Back on the subscription", "Switched to bob", None, "On API credits"]


#: The meters' accounts, which name the rows while no account has a key and no fallback block is sent.
ACCOUNTS = {"accounts": [{"id": "acct-1", "name": "alice"}, {"id": "acct-2", "name": "bob"}]}


def card(fallback, settings=None):
    return f"""
SETTINGS = {{...SETTINGS, ...{json.dumps(settings or {})}}};
LATEST = {{groups: [], accounts: {json.dumps(ACCOUNTS)}, api_fallback: {json.dumps(fallback)}}};
const card = apiFallbackCard();
paintApiFallback(card, LATEST);
const sw = all(card).find(n => n.attrs.role === 'switch');
const row = id => all(card).find(n => n.dataset.account === id);
const shownRow = id => visible(row(id));
"""


def test_the_switch_is_disabled_with_no_key_on_any_account():
    assert run(card(None, {"api_fallback": False}) + """
console.log(JSON.stringify({disabled: sw.disabled, rows: ['acct-1', 'acct-2'].map(shownRow),
  fields: tagged(card, 'input').filter(n => n.type === 'password').length}));
""") == {"disabled": True, "rows": [["alice"], ["bob"]], "fields": 2}
    nobody = [dict(k, last4=None) for k in KEYS]
    assert run(card(dict(BASE, keys=nobody), {"api_fallback": False}) + """
console.log(JSON.stringify(sw.disabled));
""") is True
    assert run(card(BASE, {"api_fallback": False}) + """
sw.events.click();
console.log(JSON.stringify({disabled: sw.disabled, pushed}));
""") == {"disabled": False, "pushed": [{"api_fallback": True}]}


SWITCH_STATE = """
const note = all(card).find(n => n.id === 'set-note-api_fallback');
console.log(JSON.stringify({disabled: sw.disabled, note: note.textContent}));
"""


def test_the_switch_waits_for_the_bridge_and_says_why():
    shown = run(card(dict(BASE, bridge=False), {"api_fallback": False}) + SWITCH_STATE)
    assert shown["disabled"] is True
    assert "the statusline bridge" in shown["note"]


def test_a_switch_already_on_can_still_be_turned_off_without_the_bridge():
    assert run(card(dict(BASE, bridge=False), {"api_fallback": True}) + SWITCH_STATE)["disabled"] is False


def test_the_table_names_its_columns():
    shown = run(card(BASE) + """
const heads = tagged(card, 'th');
console.log(JSON.stringify({heads: heads.map(n => n.textContent || n.attrs['aria-label']), scopes: heads.map(n => n.scope)}));
""")
    assert shown == {"heads": ["Account", "Key", "Spent", "Cap", "Actions"], "scopes": ["col"] * 5}


def test_each_account_has_a_row_with_its_key_and_its_cap():
    shown = run(card(BASE) + """
const cap = id => tagged(row(id), 'input').find(n => n.type === 'text').value;
console.log(JSON.stringify({rows: ['acct-1', 'acct-2', 'acct-3'].map(shownRow), caps: ['acct-1', 'acct-2'].map(cap),
  columns: ['acct-1', 'acct-3'].map(id => columns(row(id))),
  header: columns(tagged(card, 'tr')[0])}));
""")
    assert shown == {"rows": [["alice", "wxyz", "$"], ["bob", "abcd", "$"], ["Account 3"]], "caps": ["50", "20"],
                     "columns": [6, 6], "header": 6}


def test_forget_asks_once_then_names_its_account():
    shown = run(card(BASE) + """
const forget = () => labelled(row('acct-2'), 'Forget');
forget().events.click();
const asked = {posted: posted.length, word: shownRow('acct-2'), label: forget().attrs['aria-label'],
  icons: forget().children.map(n => n.dataset.icon)};
forget().events.click();
console.log(JSON.stringify({asked, posted, after: shownRow('acct-2'), icons: forget().children.map(n => n.dataset.icon)}));
""")
    assert shown == {"asked": {"posted": 0, "word": ["bob", "forget?", "abcd", "$"],
                               "label": "Forget bob's key: press again to confirm", "icons": ["check"]},
                     "posted": [["/api-fallback?token=test%20token", {"op": "forget_key", "account_id": "acct-2"}]],
                     "after": ["bob", "abcd", "$"], "icons": ["trash"]}


def test_an_armed_forget_disarms_on_blur_and_after_four_seconds():
    shown = run(card(BASE) + """
const timers = [];
setTimeout = (fn, ms) => { timers.push([fn, ms]); return timers.length; };
const forget = labelled(row('acct-1'), 'Forget');
forget.events.click();
forget.events.blur();
const blurred = {word: shownRow('acct-1'), label: forget.attrs['aria-label']};
forget.events.click();
const waits = timers.map(([, ms]) => ms);
timers.at(-1)[0]();
console.log(JSON.stringify({blurred, waits, timed: {word: shownRow('acct-1'), label: forget.attrs['aria-label']}, posted}));
""")
    disarmed = {"word": ["alice", "wxyz", "$"], "label": "Forget alice's key ending wxyz"}
    assert shown == {"blurred": disarmed, "waits": [4000, 4000], "timed": disarmed, "posted": []}


def test_saving_a_key_sends_it_once_with_its_account_and_clears_the_field():
    assert run(card(BASE, {"api_fallback": False}) + """
const field = tagged(row('acct-3'), 'input').find(n => n.type === 'password');
field.value = 'sk-ant-test-key';
tagged(row('acct-3'), 'button').find(n => n.attrs['aria-label']?.startsWith('Save')).events.click();
setTimeout(() => console.log(JSON.stringify({posted, left: field.value})), 0);
""") == {"posted": [["/api-fallback?token=test%20token", {"op": "save_key", "account_id": "acct-3", "key": "sk-ant-test-key"}]],
         "left": ""}


def test_a_refused_key_says_why_on_its_own_row():
    shown = run("reply = {error: 'the key was refused (401)'};\n" + card(BASE, {"api_fallback": False}) + """
const field = tagged(row('acct-3'), 'input').find(n => n.type === 'password');
field.value = 'sk-ant-test-key';
tagged(row('acct-3'), 'button').find(n => n.attrs['aria-label']?.startsWith('Save')).events.click();
setTimeout(() => console.log(JSON.stringify(['acct-1', 'acct-3'].map(shownRow))), 0);
""")
    assert shown == [["alice", "wxyz", "$"], ["Account 3", "the key was refused (401)"]]


def test_a_repaint_keeps_each_row_and_what_is_typed_in_it():
    assert run(card(BASE) + """
const before = row('acct-3');
const field = tagged(before, 'input').find(n => n.type === 'password');
field.value = 'sk-ant-half-typed';
paintApiFallback(card, {...LATEST, api_fallback: {...LATEST.api_fallback, phase: 'on', key_account: 'acct-1'}});
console.log(JSON.stringify({same: row('acct-3') === before, left: field.value, shown: shownRow('acct-1')}));
""") == {"same": True, "left": "sk-ant-half-typed", "shown": ["alice", "in use", "wxyz", "$0.00", "$"]}


def test_the_note_names_the_file_it_writes_and_says_when_it_is_in():
    at_rest, active = run(card(BASE) + """
const note = () => all(card).find(n => n.id === 'set-note-api_fallback').textContent;
const before = note();
paintApiFallback(card, {api_fallback: {...LATEST.api_fallback, phase: 'on'}});
console.log(JSON.stringify([before, note()]));
""")
    for text in (at_rest, active):
        assert "apiKeyHelper" in text and "~/.claude/settings.json" in text and "other machines" in text
    assert at_rest != active


def test_a_cap_is_sent_for_its_account_and_a_cap_of_none_is_refused_out_loud():
    shown = run(card(BASE) + """
const cap = tagged(row('acct-2'), 'input').find(n => n.type === 'text');
const live = all(row('acct-2')).find(n => n.attrs.role === 'status');
const was = cap.value;
cap.value = '60';
cap.events.change();
cap.value = '0';
cap.events.change();
const refused = {invalid: cap.attrs['aria-invalid'], word: shownRow('acct-2'), live: live.textContent};
paintApiFallback(card, LATEST);
const kept = cap.value;
cap.value = '25';
cap.events.keydown({key: 'Enter', preventDefault() {}});
cap.events.change();
console.log(JSON.stringify({was, refused, kept, posted: posted.map(([, body]) => body.cap_usd),
  fixed: {invalid: cap.attrs['aria-invalid'] ?? null, word: shownRow('acct-2')}}));
""")
    assert shown == {"was": "20",
                     "refused": {"invalid": "true", "word": ["bob", "too low", "abcd", "$"],
                                 "live": "The cap on bob's key must be more than $0. It stays $20."},
                     "kept": "0", "posted": [60, 25], "fixed": {"invalid": None, "word": ["bob", "abcd", "$"]}}


def test_each_row_shows_what_this_fallback_spent_on_its_key_and_which_is_in_use():
    keys = [dict(KEYS[0], spent_usd=50.4, hold={"reason": "cap", "at": NOW, "why": "cap reached"}),
            dict(KEYS[1], spent_usd=1.84), KEYS[2]]
    shown = run(card(dict(BASE, phase="on", key_account="acct-2", key_name="bob", keys=keys)) + """
const said = id => texts(row(id)).filter(t => !visible(row(id)).includes(t));
const lamp = id => all(row(id)).find(n => n.className === 'key-lamp');
const described = all(card).find(n => n.id === tagged(card, 'table')[0].attrs['aria-describedby']);
console.log(JSON.stringify({shown: ['acct-1', 'acct-2', 'acct-3'].map(shownRow), heard: ['acct-1', 'acct-2'].map(said),
  lamps: ['acct-1', 'acct-2', 'acct-3'].map(id => [lamp(id).children.map(n => n.dataset.icon), lamp(id).attrs['aria-hidden']]),
  described: described.textContent}));
""")
    assert shown["shown"] == [["alice", "cap reached", "wxyz", "$50.40", "$"], ["bob", "in use", "abcd", "$1.84", "$"],
                              ["Account 3"]]
    assert shown["heard"] == [["cap reached; skipped until an account has room or its cap is raised"], []]
    assert shown["lamps"] == [[["warning"], "true"], [["checked"], "true"], [[], "true"]]
    assert shown["described"] == ("Spent is this panel's estimate of what the fallback spent on each key; "
                                  "the Console holds the true spend.")


def test_a_failed_turn_names_its_error_under_the_idle_card():
    shown = run("""
const line = stopFailureLine({state: 'idle', stop_error: 'billing_error'});
console.log(JSON.stringify({text: line.textContent, cls: line.className, role: line.attrs.role}));
""")
    assert shown == {"text": "Turn failed: billing_error", "cls": "refusal stop-failure", "role": "status"}


def test_a_card_at_work_or_with_no_failure_says_nothing():
    assert run("""
console.log(JSON.stringify([stopFailureLine({state: 'idle'}), stopFailureLine({state: 'working', stop_error: 'x'})]));
""") == [None, None]


def test_save_is_a_floppy_disk_icon_named_for_its_account():
    assert run(card(BASE, {"api_fallback": False}) + """
const save = tagged(row('acct-3'), 'button').find(n => n.attrs['aria-label']?.startsWith('Save'));
console.log(JSON.stringify({text: save.textContent, label: save.attrs['aria-label'], title: save.title,
  icons: save.children.map(n => n.dataset.icon)}));
""") == {"text": "", "label": "Save the key for Account 3", "title": "", "icons": ["save"]}


def test_saving_shows_busy_on_the_icon_and_enter_in_the_field_saves():
    assert run(card(BASE, {"api_fallback": False}) + """
const field = tagged(row('acct-3'), 'input').find(n => n.type === 'password');
const save = tagged(row('acct-3'), 'button').find(n => n.attrs['aria-label']?.startsWith('Save'));
field.value = 'sk-ant-test-key';
field.events.keydown({key: 'Enter', preventDefault() {}});
const during = {disabled: save.disabled, busy: save.attrs['aria-busy'], label: save.attrs['aria-label'], word: shownRow('acct-3')};
setTimeout(() => console.log(JSON.stringify({during, after: {disabled: save.disabled, busy: save.attrs['aria-busy'] ?? null,
  label: save.attrs['aria-label'], word: shownRow('acct-3')}, posted: posted.length})), 0);
""") == {"during": {"disabled": True, "busy": "true", "label": "Checking the key for Account 3…",
                    "word": ["Account 3", "checking…"]},
         "after": {"disabled": False, "busy": None, "label": "Save the key for Account 3", "word": ["Account 3"]},
         "posted": 1}


def test_a_pasted_key_saves_once_and_an_empty_field_says_so():
    shown = run(card(BASE, {"api_fallback": False}) + """
const field = tagged(row('acct-3'), 'input').find(n => n.type === 'password');
const save = labelled(row('acct-3'), 'Save');
save.events.click();
const empty = {posted: posted.length, word: shownRow('acct-3')};
field.value = 'sk-ant-test-pasted';
field.events.paste();
setTimeout(() => setTimeout(() => console.log(JSON.stringify({empty, posted, left: field.value})), 0), 0);
""")
    assert shown == {"empty": {"posted": 0, "word": ["Account 3", "no key typed"]},
                     "posted": [["/api-fallback?token=test%20token",
                                 {"op": "save_key", "account_id": "acct-3", "key": "sk-ant-test-pasted"}]],
                     "left": ""}


def test_every_focus_stop_names_its_account():
    shown = run(card(BASE) + """
const shownNodes = node => node.hidden ? [] : [node, ...node.children.flatMap(shownNodes)];
const stops = id => shownNodes(row(id)).filter(n => n.tag === 'button' || n.tag === 'input').map(n => n.attrs['aria-label']);
console.log(JSON.stringify(['acct-2', 'acct-3'].map(stops)));
""")
    assert shown == [["Spend cap on bob's key, in dollars", "Forget bob's key ending abcd"],
                     ["Anthropic API key for Account 3", "Save the key for Account 3"]]


def test_a_frame_during_a_message_keeps_every_row_as_wide_as_the_header():
    shown = run(card(BASE) + """
reply = new Promise(() => {});
fetch = (url, init) => { posted.push([url, JSON.parse(init.body)]); return Promise.resolve({json: () => reply}); };
const field = tagged(row('acct-3'), 'input').find(n => n.type === 'password');
field.value = 'sk-ant-test-key';
labelled(row('acct-3'), 'Save').events.click();
labelled(row('acct-1'), 'Forget').events.click();
const cap = tagged(row('acct-2'), 'input').find(n => n.type === 'text');
cap.value = '0';
cap.events.change();
paintApiFallback(card, {...LATEST, api_fallback: {...LATEST.api_fallback, phase: 'on', key_account: 'acct-1'}});
console.log(JSON.stringify({columns: ['acct-1', 'acct-2', 'acct-3'].map(id => columns(row(id))),
  shown: ['acct-1', 'acct-2', 'acct-3'].map(shownRow)}));
""")
    assert shown == {"columns": [6, 6, 6],
                     "shown": [["alice", "forget?", "wxyz", "$0.00", "$"], ["bob", "too low", "abcd", "$"],
                               ["Account 3", "checking…"]]}


def test_the_key_column_folds_in_a_narrow_panel_at_any_text_size():
    """By a class syncCompact sets from the panel's width over the text size: a
    container query stops matching under the text size's zoom in this WebKit."""
    consts = "\n".join(re.search(rf"^const {name} = \d+;$", PAGE, re.M).group(0)
                       for name in ("COMPACT_BELOW", "COMPACT_ABOVE", "TINY_BELOW", "TINY_ABOVE",
                                    "BARE_ACTS_BELOW", "BARE_ACTS_ABOVE", "KEYS_FOLD_BELOW"))
    shown = run(consts + "\n" + function(PAGE, "syncCompact") + """
let compact = false, tiny = false, bareActs = false, compactLimitsOpen = false, uiScale = 1;
const classes = new Set();
document.documentElement = {classList: {toggle: (c, on) => on ? classes.add(c) : classes.delete(c)}};
const paintBudget = () => {}, render = () => {}, lastSnapshot = null;
const window = {innerWidth: 0};
const folded = (width, scale) => { window.innerWidth = width; uiScale = scale; syncCompact(); return classes.has('keys-fold'); };
console.log(JSON.stringify([folded(380, 1), folded(250, 1), folded(300, 1.2), folded(380, 1)]));
""")
    assert shown == [False, True, True, False]
