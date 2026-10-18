# ABOUTME: Puts the word Done into the iTerm2 pane of a session whose turn ended while nobody
# ABOUTME: looked, as the pane's badge or a green tab, and takes it back the moment the pane is seen.
"""Every mark is a view of `alerts.Unseen.sids`: a rebuild says which sessions
want a mark on each channel, the marker diffs that against what it has
marked, writes the new ones and restores the gone ones. What it writes goes
through the session's own profile, so the saved profile is untouched, and
what it overwrote is kept for the restore. An iTerm2 call that fails drops
that session's mark and is logged; the rebuild never fails for a mark.
"""

#: The word, exactly: the startup sweep recognises a mark by it.
WORD = "Done"

#: The panel's calm green, the dark theme's --sev-ok, as a tab colour.
TAB_RGB = (48, 209, 88)
#: The same green at about a third, as the badge's ink: the badge is large
#: and sits over the pane's output, and the profile's own colour (often a
#: red) reads as an error. Written to all three colour fields: a profile
#: with separate light and dark colours shows those two and ignores the
#: plain one. Size, font and margins cannot be set per session: iTerm2
#: takes them and ignores them, so the saved profile's badge settings
#: decide those.
BADGE_RGBA = (48, 209, 88, 90)
BADGE_COLOURS = ("badge_color", "badge_color_light", "badge_color_dark")

#: Channel -> the setting that turns it on and the profile fields it touches.
CHANNELS = {
    "badge": ("mark_badge", ("badge_text",) + BADGE_COLOURS),
    "tab": ("mark_tab", ("use_tab_color", "tab_color")),
}


def wanted(rows, unseen, settings):
    """{channel: the session ids that want its mark}, channels that are off
    left out. Unseen alone decides: it drops a sid that began a turn, blocked
    or exited, and keeps one through the few seconds a Stop hook's command
    reads as working, which the mark rides out too. Only a card can carry a
    mark: a teammate's row never shows Done, so its pane must not either; a
    docked worktree or a linked partner is a card of its own."""
    cards = {row["session_id"] for row in rows if not row["depth"] and row["session_id"] in unseen}
    return {channel: set(cards) for channel, (setting, _) in CHANNELS.items() if settings[setting] and cards}


def plan(want, have):
    """-> (the ids to mark, the ids to clear)."""
    return want - have, have - want


class Marker:
    def __init__(self, api=None):
        #: session id -> channel -> {field: the value the mark replaced}.
        self.have = {}
        #: Whether the sweep for a dead daemon's marks has run.
        self.swept = False
        #: The sessions logged as busy on a channel, so it is said once.
        self.busy = set()
        self._api = api

    @property
    def api(self):
        """The iterm2 package, imported on first use: the tests never have it,
        and the daemon imports it only once iTerm2 is there to talk to."""
        if self._api is None:
            import iterm2
            self._api = iterm2
        return self._api

    async def step(self, app, rows, unseen, settings, log):
        """Bring the panes into line with one reading: `rows` are the agent
        rows after the band, `unseen` is Unseen.sids, `settings` the ones
        read for this rebuild. `log` takes one line."""
        if not self.swept:
            await self.sweep(app, log)
            self.swept = True
        want = wanted(rows, unseen, settings)
        for channel in CHANNELS:
            marked = {sid for sid, channels in self.have.items() if channel in channels}
            to_mark, to_clear = plan(want.get(channel, set()), marked)
            for sid in to_clear:
                session = app.get_session_by_id(sid)
                kept = self.have[sid].pop(channel)
                if not self.have[sid]:
                    del self.have[sid]
                if session is not None:
                    await self.restore(session, channel, kept, log)
            for sid in to_mark:
                session = app.get_session_by_id(sid)
                if session is None:
                    continue
                kept = await self.write(session, channel, log)
                if kept is not None:
                    self.have.setdefault(sid, {})[channel] = kept

    async def sweep(self, app, log):
        """Clear the word a daemon that died left as a badge: the marker never
        writes anything else there, and nobody types it by hand."""
        for window in app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    try:
                        profile = await session.async_get_profile()
                        if profile.badge_text != WORD:
                            continue
                        local = self.api.LocalWriteOnlyProfile()
                        local.set_badge_text("")
                        await session.async_set_profile_properties(local)
                    except Exception as error:  # noqa: BLE001 -- an iTerm2 call; the rebuild goes on
                        log(f"sweep {session.session_id[:8]}: {error!r}")
                        continue
                    log(f"swept {session.session_id[:8]} badge_text")

    async def write(self, session, channel, log):
        """Put the mark on one channel of one session. -> the values it
        replaced, or None when nothing was written: the field is in use
        (said once per session and channel) or iTerm2 refused."""
        sid = session.session_id
        try:
            profile = await session.async_get_profile()
            local = self.api.LocalWriteOnlyProfile()
            if channel == "badge":
                if profile.badge_text:
                    if (sid, channel) not in self.busy:
                        self.busy.add((sid, channel))
                        log(f"badge busy {sid[:8]}")
                    return None
                # A profile without the key reads None; what goes back is the empty badge.
                kept = {"badge_text": profile.badge_text or ""}
                kept.update({field: getattr(profile, field) for field in BADGE_COLOURS})
                local.set_badge_text(WORD)
                for field in BADGE_COLOURS:
                    getattr(local, "set_" + field)(self.api.Color(*BADGE_RGBA))
            else:
                if profile.use_tab_color:
                    if (sid, channel) not in self.busy:
                        self.busy.add((sid, channel))
                        log(f"tab busy {sid[:8]}")
                    return None
                kept = {"use_tab_color": bool(profile.use_tab_color), "tab_color": profile.tab_color}
                local.set_use_tab_color(True)
                local.set_tab_color(self.api.Color(*TAB_RGB))
            await session.async_set_profile_properties(local)
        except Exception as error:  # noqa: BLE001 -- an iTerm2 call; the rebuild goes on
            log(f"mark {channel} {sid[:8]}: {error!r}")
            return None
        self.busy.discard((sid, channel))
        return kept

    async def restore(self, session, channel, kept, log):
        """Write back what the mark replaced on one channel."""
        try:
            local = self.api.LocalWriteOnlyProfile()
            if channel == "badge":
                local.set_badge_text(kept["badge_text"])
                for field in BADGE_COLOURS:
                    getattr(local, "set_" + field)(kept[field])
            else:
                local.set_use_tab_color(kept["use_tab_color"])
                local.set_tab_color(kept["tab_color"])
            await session.async_set_profile_properties(local)
        except Exception as error:  # noqa: BLE001 -- an iTerm2 call; the rebuild goes on
            log(f"clear {channel} {session.session_id[:8]}: {error!r}")
