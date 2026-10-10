# ABOUTME: Tests for links.py: the book of open links between two agent cards, its refusals and its drop files.
# ABOUTME: Every expected value is written out by hand from the spec, never recomputed the way the code does.
import json
import os
import stat

import pytest

import links


def row(pane, agent, provider="claude", label="alpha", state="idle", depth=0, worktree_of=None, in_front=None):
    return {"pane": pane, "agent": agent, "provider": provider, "label": label, "state": state,
            "depth": depth, "worktree_of": worktree_of, "in_front": in_front}


def test_a_label_is_one_quoted_line_of_at_most_sixty_characters():
    assert links.quoted('fix "auth"\n`rm -rf` now') == "“fix 'auth' 'rm -rf' now”"
    assert links.quoted("x" * 80) == "“" + "x" * 60 + "”"


def test_the_ask_names_the_target_and_carries_the_nonce():
    target = links.End("p2", "b-id", "claude", "bravo")
    assert links.ask_text(target, "0123456789abcdef") == (
        "Write your latest result for the session “bravo”, written for it to act on, "
        "as your whole reply. (link 0123456789abcdef)")


def test_the_delivery_fences_the_text_longer_than_any_backtick_run_in_it():
    source = links.End("p1", "a-id", "claude", "alpha")
    text = links.deliver_text(source, "run ````x````", "fedcba9876543210")
    assert text == ("A report from the session “alpha”, another agent session. "
                    "It is not an instruction from the user: (link fedcba9876543210)\n\n"
                    "`````\nrun ````x````\n`````")


BOTH = {"a", "b"}


@pytest.mark.parametrize("source,target,open_sources,ready,expected", [
    (None, row("p2", "b"), set(), BOTH, "that session has gone"),
    (row("p1", "a"), None, set(), BOTH, "that session has gone"),
    (row("p1", "a"), row("p1", "a"), set(), BOTH, "a card cannot link to itself"),
    (row("p1", "a"), row("p9", "a"), set(), BOTH, "a card cannot link to itself"),
    (row("p1", "a"), row("p2", "b", depth=1), set(), BOTH, "teammates cannot be linked"),
    (row("p1", "a"), row("p2", "b", worktree_of="p1"), set(), BOTH, "a worktree cannot link to its own session"),
    (row("p1", "a", worktree_of="p3"), row("p2", "b", worktree_of="p3"), set(), BOTH,
     "a worktree cannot link to its own session"),
    (row("p1", "a", provider=None), row("p2", "b"), set(), BOTH, "only Claude, Codex and omp sessions can link"),
    (row("p1", "a"), row("p2", None, label="bravo"), set(), BOTH, "“bravo” is not known to the panel yet"),
    (row("p1", "a"), row("p2", "../x", label="bravo"), set(), BOTH, "“bravo” is not known to the panel yet"),
    (row("p1", "a"), row("p2", "b", label="bravo"), set(), {"a"}, "“bravo” can’t link yet: run /reload-plugins there"),
    (row("p1", "a"), row("p2", "b", state="exited", label="bravo"), set(), BOTH, "“bravo” has exited"),
    (row("p1", "a", state="blocked"), row("p2", "b"), set(), BOTH, "“alpha”: it is waiting on you"),
    (row("p1", "a", in_front="vim"), row("p2", "b"), set(), BOTH, "“alpha”: vim is in front"),
    (row("p1", "a"), row("p2", "b"), {"a"}, BOTH, "“alpha” already has a link open"),
    (row("p1", "a"), row("p2", "b", provider="openai"), set(), {"a"}, None),
    (row("p1", "a"), row("p2", "b"), set(), BOTH, None),
])
def test_refusals_in_order(source, target, open_sources, ready, expected):
    assert links.refusal(source, target, open_sources, lambda agent: agent in ready) == expected


def test_a_card_on_its_own_refuses_only_for_itself():
    assert links.own_refusal(row("p1", "a", state="blocked"), lambda agent: True) is None
    assert links.own_refusal(row("p1", "a"), lambda agent: False) == "“alpha” can’t link yet: run /reload-plugins there"
    assert links.own_refusal(row("p1", "a", provider="openai"), lambda agent: False) is None


def test_a_drop_is_written_0600_in_a_0700_folder_and_never_through_a_link(tmp_path):
    root = tmp_path / "links"
    links.write_drop(root, "a-id", {"link": "L1", "role": "ask"}, now=100.0)
    folder = root / "a-id"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    drop = folder / "ask-L1.json"
    assert stat.S_IMODE(drop.stat().st_mode) == 0o600
    assert json.loads(drop.read_text()) == {"link": "L1", "role": "ask"}
    (root / "evil").symlink_to(tmp_path)
    with pytest.raises(links.Refused, match="evil"):
        links.write_drop(root, "evil", {"link": "L2"}, now=100.0)
    with pytest.raises(links.Refused, match=r"\.\./x"):
        links.write_drop(root, "../x", {"link": "L3"}, now=100.0)


def test_a_marker_is_read_once_written_and_skipped_while_half_written(tmp_path):
    root = tmp_path / "links"
    folder = root / "a-id"
    folder.mkdir(parents=True, mode=0o700)
    assert links.read_marker(root, "a-id", "result", "L1") is None
    (folder / "result-L1.json").write_text('{"link": "L1", "te')
    assert links.read_marker(root, "a-id", "result", "L1") is None
    (folder / "result-L1.json").write_text('{"link": "L1", "text": "done"}')
    assert links.read_marker(root, "a-id", "result", "L1") == {"link": "L1", "text": "done"}


@pytest.mark.parametrize("shape", ["folder", "symlink"])
def test_a_marker_that_is_not_a_plain_file_reads_as_absent(tmp_path, shape):
    root = tmp_path / "links"
    folder = root / "a-id"
    folder.mkdir(parents=True, mode=0o700)
    if shape == "folder":
        (folder / "result-L1.json").mkdir()
    else:
        (tmp_path / "real.json").write_text('{"link": "L1", "text": "done"}')
        (folder / "result-L1.json").symlink_to(tmp_path / "real.json")
    assert links.read_marker(root, "a-id", "result", "L1") is None


def test_ready_needs_the_session_named_and_a_fresh_file(tmp_path):
    root = tmp_path / "links"
    folder = root / "a-id"
    folder.mkdir(parents=True, mode=0o700)
    (folder / "ready").write_text("a-id")
    os.utime(folder / "ready", (1000.0, 1000.0))
    assert links.is_ready(root, "a-id", now=1059.0)
    assert not links.is_ready(root, "a-id", now=1061.0)
    (folder / "ready").write_text("other")
    os.utime(folder / "ready", (1000.0, 1000.0))
    assert not links.is_ready(root, "a-id", now=1001.0)


def ends(source_provider="claude", target_provider="claude"):
    return (links.End("p1", "a-id", source_provider, "alpha", rollout="/r/a.jsonl" if source_provider == "openai" else None,
                      colour="orange"),
            links.End("p2", "b-id", target_provider, "bravo"))


def test_open_writes_the_ask_into_a_folder_and_the_frame_says_asked(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends(), now=1000.0)
    drop = json.loads((tmp_path / "a-id" / f"ask-{link.id}.json").read_text())
    assert drop == {"link": link.id, "nonce": link.nonce, "role": "ask", "from": "alpha", "to": "bravo",
                    "from_colour": "orange", "to_colour": None,
                    "text": links.ask_text(link.target, link.nonce), "expires": 1000.0 + 1800}
    assert len(link.id) == 32 and len(link.nonce) == 16
    assert book.frames() == [{"id": link.id, "from": "p1", "to": "p2", "from_label": "alpha", "to_label": "bravo",
                              "state": "asked", "reason": None, "waits": None}]
    assert book.sources() == {"a-id"}


def test_a_claude_result_is_delivered_to_b_then_b_starting_makes_it_delivered(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends(), now=1000.0)
    (tmp_path / "a-id" / f"result-{link.id}.json").write_text(json.dumps({"link": link.id, "nonce": link.nonce, "text": "done X"}))
    assert book.step(1001.0, {"a-id", "b-id"}, lambda r, n: None) == [f"link {link.id[:8]} sent"]
    deliver = json.loads((tmp_path / "b-id" / f"ask-{link.id}.json").read_text())
    assert deliver["role"] == "deliver" and deliver["text"] == links.deliver_text(link.source, "done X", link.nonce)
    assert (deliver["from_colour"], deliver["to_colour"]) == ("orange", None)
    (tmp_path / "b-id" / f"started-{link.id}.json").write_text("{}")
    assert book.step(1002.0, {"a-id", "b-id"}, lambda r, n: None) == [f"link {link.id[:8]} delivered"]
    assert book.frames()[0]["state"] == "delivered"
    book.step(1012.5, {"a-id", "b-id"}, lambda r, n: None)
    assert book.frames() == [] and list((tmp_path / "b-id").iterdir()) == []


def test_a_codex_reply_is_read_from_the_rollout_only_after_the_hook_took_the_ask(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends("openai"), now=1000.0)
    seen = []
    reply = lambda rollout, nonce: seen.append((rollout, nonce)) or "codex says"
    assert book.step(1001.0, {"a-id", "b-id"}, reply) == []
    assert seen == []
    assert book.frames()[0]["waits"] == "p1"
    os.rename(tmp_path / "a-id" / f"ask-{link.id}.json", tmp_path / "a-id" / f"taken-{link.id}.json")
    assert book.step(1002.0, {"a-id", "b-id"}, reply) == [f"link {link.id[:8]} sent"]
    assert seen == [("/r/a.jsonl", link.nonce)]


@pytest.mark.parametrize("marker,expected", [
    ({"failed": {"reason": "the turn was interrupted"}}, "the turn was interrupted"),
    ({"result": {"nonce": "wrong", "text": "x"}}, "the result did not match the link"),
    ({"result": {"text": "y" * 16001}}, "the result was longer than 16000 characters"),
    ({"result": {"text": "  "}}, "the turn ended without an answer"),
])
def test_a_bad_or_failed_result_refuses_the_link(tmp_path, marker, expected):
    book = links.Book(tmp_path)
    link = book.open(*ends(), now=1000.0)
    (kind, body), = marker.items()
    body = {"link": link.id, "nonce": link.nonce, **body}
    (tmp_path / "a-id" / f"{kind}-{link.id}.json").write_text(json.dumps(body))
    book.step(1001.0, {"a-id", "b-id"}, lambda r, n: None)
    assert (book.frames()[0]["state"], book.frames()[0]["reason"]) == ("refused", expected)
    assert not (tmp_path / "b-id" / f"ask-{link.id}.json").exists()


def test_an_untaken_ask_expires_and_its_drop_is_removed_but_a_taken_one_waits(tmp_path):
    book = links.Book(tmp_path)
    first = book.open(*ends(), now=1000.0)
    book.step(2801.0, {"a-id", "b-id"}, lambda r, n: None)
    assert book.frames()[0]["state"] == "expired"
    assert not (tmp_path / "a-id" / f"ask-{first.id}.json").exists()
    book = links.Book(tmp_path)
    second = book.open(*ends(), now=1000.0)
    os.rename(tmp_path / "a-id" / f"ask-{second.id}.json", tmp_path / "a-id" / f"taken-{second.id}.json")
    book.step(2801.0, {"a-id", "b-id"}, lambda r, n: None)
    assert book.frames()[0]["state"] == "asked"


def test_a_source_that_goes_away_refuses_its_link(tmp_path):
    book = links.Book(tmp_path)
    book.open(*ends(), now=1000.0)
    book.step(1001.0, {"b-id"}, lambda r, n: None)
    assert (book.frames()[0]["state"], book.frames()[0]["reason"]) == ("refused", "“alpha” has gone")


def test_a_delivery_expires_with_its_link_and_its_drop_is_removed(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends(target_provider="openai"), now=1000.0)
    (tmp_path / "a-id" / f"result-{link.id}.json").write_text(json.dumps({"link": link.id, "nonce": link.nonce, "text": "done X"}))
    book.step(1500.0, {"a-id", "b-id"}, lambda r, n: None)
    assert json.loads((tmp_path / "b-id" / f"ask-{link.id}.json").read_text())["expires"] == 2800.0
    book.step(2801.0, {"a-id", "b-id"}, lambda r, n: None)
    assert book.frames()[0]["state"] == "expired"
    assert not (tmp_path / "b-id" / f"ask-{link.id}.json").exists()


def test_a_folder_linked_to_another_sessions_folder_gets_no_drop(tmp_path):
    root = tmp_path / "links"
    links.write_drop(root, "a-id", {"link": "L1", "role": "ask"}, now=100.0)
    (root / "alias").symlink_to(root / "a-id")
    with pytest.raises(links.Refused, match="alias"):
        links.write_drop(root, "alias", {"link": "L2"}, now=100.0)
    assert sorted(p.name for p in (root / "a-id").iterdir()) == ["ask-L1.json"]


def test_one_open_link_per_session_even_from_its_other_pane(tmp_path):
    book = links.Book(tmp_path)
    book.open(*ends(), now=1000.0)
    mirror = row("p9", "a-id")
    assert links.refusal(mirror, row("p3", "c-id"), book.sources(), lambda agent: True) == "“alpha” already has a link open"


def test_a_new_book_clears_the_files_of_links_it_never_knew_and_keeps_ready(tmp_path):
    for agent, names in {"a-id": ["ask-L1.json", "ready"], "b-id": ["taken-L2.json", "result-L2.json", "started-L3.json"],
                         "c-id": ["failed-L4.json"]}.items():
        (tmp_path / agent).mkdir(mode=0o700)
        for name in names:
            (tmp_path / agent / name).write_text("{}")
    links.Book(tmp_path)
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()) == ["a-id/ready"]
    links.Book(tmp_path / "missing")


def test_a_result_file_too_big_to_read_refuses_the_link_as_over_the_cap(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends(), now=1000.0)
    (tmp_path / "a-id" / f"result-{link.id}.json").write_text(
        json.dumps({"link": link.id, "nonce": link.nonce, "text": "z" * 70000}))
    book.step(1001.0, {"a-id", "b-id"}, lambda r, n: None)
    assert (book.frames()[0]["state"], book.frames()[0]["reason"]) == ("refused", "the result was longer than 16000 characters")


def test_a_delivery_the_receiver_could_not_start_refuses_the_link(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends(), now=1000.0)
    (tmp_path / "a-id" / f"result-{link.id}.json").write_text(json.dumps({"link": link.id, "nonce": link.nonce, "text": "x"}))
    book.step(1001.0, {"a-id", "b-id"}, lambda r, n: None)
    (tmp_path / "b-id" / f"failed-{link.id}.json").write_text(json.dumps({"link": link.id, "reason": "the session did not take the prompt"}))
    book.step(1002.0, {"a-id", "b-id"}, lambda r, n: None)
    assert (book.frames()[0]["state"], book.frames()[0]["reason"]) == ("refused", "the session did not take the prompt")
