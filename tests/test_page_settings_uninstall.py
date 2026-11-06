# ABOUTME: Runs the Settings uninstall controls under Node with the page's function harness.
# ABOUTME: Covers confirmation, cancellation and server replies without contacting a daemon.
import json
import subprocess
from pathlib import Path

import pytest

from page_source import function


PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text()
DOM = """
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = {};
    this.textContent = ''; this.className = ''; this.id = ''; this.disabled = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(name, fn) { this.events[name] = fn; }
  contains(target) { return this === target || this.children.some(n => n.contains(target)); }
  focus() { focused = this; }
  querySelector(selector) { return this.children.find(n => n.tag === selector) || null; }
}
let focused = null, row;
const document = {createElement: tag => new Node(tag), getElementById: () => row};
const TOKEN = 'test token';
let LATEST = {accounts: {accounts: []}};
let UNINSTALL = {state: 'idle'};
const texts = node => [node.textContent, ...node.children.flatMap(texts)].filter(Boolean);
const buttons = node => [...(node.tag === 'button' ? [node] : []), ...node.children.flatMap(buttons)];
const actions = node => buttons(node).filter(n => n.attrs.role !== 'switch');
const switches = node => buttons(node).filter(n => n.attrs.role === 'switch');
const named = (node, text) => buttons(node).find(n => n.textContent === text);
const notice = node => texts(node).find(t => t.startsWith('Your '));
const find = (node, pick) => pick(node) ? node : node.children.map(n => find(n, pick)).find(Boolean);
"""


def run(body, names=("uninstallRow", "paintUninstall", "cancelUninstall", "dismissUninstall", "uninstallPanel")):
    script = "\n".join([DOM, *(function(PAGE, name) for name in names), body])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


@pytest.mark.parametrize(("snapshot", "notice"), [
    ({"accounts": []}, []),
    ({"accounts": [{"needs_login": True}]}, ["Your 1 saved account login is deleted too."]),
    ({"accounts": [{}, {"needs_login": True}, {"error": "unreadable"}]},
     ["Your 3 saved account logins are deleted too."]),
    (None, ["Your saved account logins are deleted too."]),
    ({"accounts": [], "error": "unreadable store"}, ["Your saved account logins are deleted too."]),
])
def test_uninstall_opens_an_in_place_confirmation_with_its_scope(snapshot, notice):
    assert run(f"LATEST.accounts = {json.dumps(snapshot)};\n" + """
row = uninstallRow();
const before = texts(row);
buttons(row)[0].events.click();
console.log(JSON.stringify({before, after: texts(row), focused: focused.textContent,
                            keep: switches(row).map(n => [n.type, n.className, n.attrs])}));
""") == {
        "before": ["Uninstall the panel…"],
        "after": ["Uninstall the panel?", "Removes the panel, hooks, settings and state; keeps the checkout.",
                  "Keep my account logins", *notice, "Cancel", "Uninstall"],
        "focused": "Cancel", "keep": [["button", "sw", {
            "role": "switch", "aria-label": "Keep my account logins", "aria-checked": "false"}]]}


def test_keep_switch_updates_the_notice_both_ways_without_replacing_the_control():
    assert run("""
LATEST.accounts.accounts = [{}];
row = uninstallRow();
actions(row)[0].events.click();
const sw = switches(row)[0];
sw.focus();
const seen = [];
for (let i = 0; i < 3; i++) {
  if (i) sw.events.click();
  seen.push([sw.attrs['aria-checked'], notice(row), focused === sw, switches(row)[0] === sw]);
}
const label = find(row, n => n.tag === 'label');
console.log(JSON.stringify({seen, label: label.children.map(n => [n.tag, n.textContent])}));
""") == {
        "seen": [["false", "Your 1 saved account login is deleted too.", True, True],
                 ["true", "Your 1 saved account login is kept.", True, True],
                 ["false", "Your 1 saved account login is deleted too.", True, True]],
        "label": [["span", "Keep my account logins"], ["span", "Your 1 saved account login is deleted too."],
                  ["button", ""]]}


def test_cancel_escape_and_outside_click_return_to_the_uninstall_button():
    assert run("""
row = uninstallRow();
const seen = [];
for (const how of ['button', 'escape', 'outside']) {
  actions(row)[0].events.click();
  switches(row)[0].events.click();
  if (how === 'button') named(row, 'Cancel').events.click();
  if (how === 'escape') dismissUninstall({type: 'keydown', key: 'Escape'});
  if (how === 'outside') dismissUninstall({type: 'pointerdown', target: new Node('div')});
  seen.push(texts(row));
  actions(row)[0].events.click();
  seen.push(switches(row)[0].attrs['aria-checked']);
  cancelUninstall();
}
console.log(JSON.stringify(seen));
""") == [
        ["Uninstall the panel…"], "false", ["Uninstall the panel…"], "false", ["Uninstall the panel…"], "false"]


@pytest.mark.parametrize("keep_accounts", [False, True])
def test_confirm_posts_once_and_shows_the_log_after_acceptance(keep_accounts):
    assert run(f"const keepAccounts = {json.dumps(keep_accounts)};\n" + """
const calls = [];
let answer;
const fetch = (...args) => { calls.push(args); return new Promise(resolve => answer = resolve); };
(async () => {
  LATEST.accounts.accounts = [{}, {}];
  row = uninstallRow();
  buttons(row)[0].events.click();
  const sw = switches(row)[0];
  sw.focus();
  if (keepAccounts) sw.events.click();
  const choice = [notice(row), focused === sw, switches(row)[0] === sw];
  const pending = named(row, 'Uninstall').events.click();
  const disabled = buttons(row).map(b => b.disabled);
  uninstallPanel();
  answer({status: 202, text: async () => JSON.stringify({log: '/tmp/uninstall.log'})});
  await pending;
  console.log(JSON.stringify({calls, choice, disabled, after: texts(row)}));
})();
""", names=("uninstallRow", "paintUninstall", "cancelUninstall", "uninstallPanel")) == {
        "calls": [["/uninstall?token=test%20token", {"method": "POST",
                   "body": json.dumps({"keep_accounts": keep_accounts}, separators=(",", ":"))}]],
        "choice": [f"Your 2 saved account logins are {'kept' if keep_accounts else 'deleted too'}.", True, True],
        "disabled": [True, True, True],
        "after": ["Uninstalling the panel", "The panel stops when it is done. Its log:", "/tmp/uninstall.log"]}


@pytest.mark.parametrize(("reply", "reason"), [
    ("Promise.resolve({status: 403, text: async () => 'forbidden'})", "forbidden"),
    ("Promise.resolve({status: 409, text: async () => '{\"error\":\"cannot create log\"}'})", "cannot create log"),
    ("Promise.reject(new Error('connection refused'))", "connection refused"),
])
def test_a_refused_or_failed_post_keeps_confirmation_and_its_reason(reply, reason):
    assert run(f"""
const calls = [];
const fetch = (...args) => {{ calls.push(args); return {reply}; }};
(async () => {{
  LATEST.accounts.accounts = [{{}}];
  row = uninstallRow();
  buttons(row)[0].events.click();
  switches(row)[0].events.click();
  await named(row, 'Uninstall').events.click();
  await named(row, 'Uninstall').events.click();
  console.log(JSON.stringify({{text: texts(row), disabled: buttons(row).map(b => b.disabled),
                              kept: switches(row)[0].attrs['aria-checked'], calls}}));
}})();
""") == {
        "text": ["Uninstall the panel?", "Removes the panel, hooks, settings and state; keeps the checkout.",
                 "Keep my account logins", "Your 1 saved account login is kept.", reason, "Cancel", "Uninstall"],
        "disabled": [False, False, False], "kept": "true",
        "calls": [["/uninstall?token=test%20token", {"method": "POST", "body": '{"keep_accounts":true}'}]] * 2}
