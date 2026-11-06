# ABOUTME: Paints each card's iTerm2 tab in its cs session colour, 35% over the pane's own backgrounds,
# ABOUTME: and puts back what the paint replaced when the setting goes off, the card goes or its colour changes.

from dataclasses import dataclass

#: Claude Code's own /color palette as cs keeps it (_session_color_rgb in ~/.local/bin/cs, which cs keeps
#: in step with bin/cs-statusline's _sgr). Not page.html's SESSION_COLOURS: the same names, other values.
PALETTE = {"red": (220, 38, 38), "blue": (106, 155, 204), "green": (22, 163, 74), "yellow": (202, 138, 4),
           "purple": (130, 125, 189), "orange": (217, 119, 87), "pink": (196, 102, 134), "cyan": (8, 145, 178)}

#: Percent of the session colour over the background, picked on a live tab.
SHARE = 35

#: Variant -> (its tab colour, the switch that shows it, the background it sits on), as iterm2.Profile names
#: them; each setter is "set_" + the name. A profile with separate light and dark colours shows the light
#: and dark ones, either at any moment, and ignores the plain one.
VARIANTS = {"plain": ("tab_color", "use_tab_color", "background_color"),
            "light": ("tab_color_light", "use_tab_color_light", "background_color_light"),
            "dark": ("tab_color_dark", "use_tab_color_dark", "background_color_dark")}


def mix(colour, background):
    """SHARE percent of `colour` over `background`, per channel, a half rounding up. In whole numbers, so a
    restarted daemon finds its own mix to the unit."""
    return tuple((SHARE * c + (100 - SHARE) * b + 50) // 100 for c, b in zip(colour, background))


def wanted(rows, settings):
    """{session id: the palette name its tab wears}; nothing while the setting is off. Only a card's own pane
    takes a colour: a teammate's leaves its tab alone. Each card on a pane votes with its colour, or against
    when it has none in the palette or runs on another machine; the tab takes a colour only when every vote
    names it, since in plain tmux one pane hosts several cards and a tab in one's colour names the others
    wrongly."""
    if not settings["tab_colour"]:
        return {}
    votes = {}
    for row in rows:
        if row["depth"]:
            continue
        colour = row.get("colour")
        votes.setdefault(row["session_id"], set()).add(None if row.get("host") or colour not in PALETTE else colour)
    return {sid: names.pop() for sid, names in votes.items() if len(names) == 1 and None not in names}


@dataclass(frozen=True)
class Slot:
    """One variant of a pane's tab colour as its profile holds it."""
    on: bool
    #: The iterm2.Color the profile handed out, kept so it goes back unchanged; None when it has none.
    colour: object
    #: That colour rounded to whole channels, for comparing; None when it has none.
    rgb: tuple | None
    #: The background the variant sits on, rounded; None when the profile has none.
    background: tuple | None


@dataclass(frozen=True)
class TabColour:
    """A pane's tab colour fields, read once from its profile."""
    separate: bool
    slots: dict

    @property
    def shown(self):
        """The variants iTerm2 can show, as sidebar.terminal_background picks its background."""
        return ("light", "dark") if self.separate else ("plain",)


def _rgb(colour):
    return None if colour is None else tuple(round(c) for c in (colour.red, colour.green, colour.blue))


def read_tab(profile):
    """iterm2.Profile -> TabColour. A key the profile lacks reads None, a switch among them, which is off.
    Colours are rounded and their colour space ignored, as sidebar.terminal_background does."""
    return TabColour(bool(profile.use_separate_colors_for_light_and_dark_mode),
                     {variant: Slot(bool(getattr(profile, use)), getattr(profile, tab), _rgb(getattr(profile, tab)),
                                    _rgb(getattr(profile, background)))
                      for variant, (tab, use, background) in VARIANTS.items()})


@dataclass(frozen=True)
class Layer:
    """One variant painted."""
    #: The mix written there, its switch on.
    wrote: tuple
    #: The iterm2.Color it replaced; None when it held none, or a paint of ours, and nothing goes back.
    kept: object


@dataclass(frozen=True)
class Painted:
    name: str
    #: variant -> Layer, for every variant written.
    layers: dict


@dataclass(frozen=True)
class Left:
    """A tab not painted for `name`, and why, said once: nothing is tried again until its card wants another
    colour, so a rebuild makes no call for it."""
    name: str
    #: "own", "no background", "recoloured" or "failed".
    why: str


def paint_name(slot):
    """The palette name whose mix over the slot's own background its colour is, switch on or off, or None:
    the colours this module writes are the only way a restarted daemon knows its own paint."""
    if slot.rgb is None or slot.background is None:
        return None
    return next((name for name, colour in PALETTE.items() if mix(colour, slot.background) == slot.rgb), None)


def recognise(tab):
    """The paint a daemon that died left: every variant the tab shows wears one name's mix, its switch on.
    What it replaced is unknown, so it is kept as nothing: the switches go back off and the paint stays,
    unseen."""
    def shows(slot, name):
        return slot.on and paint_name(slot) == name
    name = next((name for name in PALETTE if all(shows(tab.slots[variant], name) for variant in tab.shown)), None)
    if name is None:
        return None
    return Painted(name, {variant: Layer(slot.rgb, None) for variant, slot in tab.slots.items() if shows(slot, name)})


def still_ours(tab, painted):
    """Whether every variant painted still shows what was written there, its switch on. One changed (the tab
    menu's colour picker, a profile switched under it) and the tab is someone else's."""
    return all(tab.slots[variant].on and tab.slots[variant].rgb == layer.wrote
               for variant, layer in painted.layers.items())


def original_colour(slot):
    """What a first paint of the slot keeps to put back: the profile's colour, or nothing when the field
    holds a paint of ours, so a paint is never given back as the profile's own."""
    return None if paint_name(slot) else slot.colour


def decide(tab, name, kept):
    """The paint for `name` on this tab, or why there is none. `kept` holds what a paint still on the tab
    replaced, by variant. A variant showing a colour of its own is never written: when iTerm2 shows it, the
    whole tab keeps its own. Nor is one with no background to mix over, and a tab that shows such a one is
    left alone, since a guessed background is a colour nobody picked."""
    layers = {}
    for variant, slot in tab.slots.items():
        own = variant not in kept and slot.on and slot.colour is not None and paint_name(slot) is None
        if own and variant in tab.shown:
            return Left(name, "own")
        if own or slot.background is None:
            continue
        layers[variant] = Layer(mix(PALETTE[name], slot.background), kept.get(variant, original_colour(slot)))
    if not set(tab.shown) <= layers.keys():
        return Left(name, "no background")
    return Painted(name, layers)


class Painter:
    """Brings every card's tab colour into line with one reading. A rebuild where no card's colour changed
    makes no iTerm2 call; every touch of a tab reads it first, so a colour someone else gave it is never
    written over or put back. An iTerm2 call that fails drops that tab's paint and is logged; the rebuild
    never fails for it. Nothing is taken back when the daemon stops: the next one adopts the paint."""

    def __init__(self, api=None):
        #: session id -> what its tab wears: Painted, or Left with why not.
        self.have = {}
        #: Whether the read of every pane for a dead daemon's paint has run.
        self.adopted = False
        self._api = api

    @property
    def api(self):
        """The iterm2 package, imported on first use: the tests never have it, and the daemon imports it only
        once iTerm2 is there to talk to."""
        if self._api is None:
            import iterm2
            self._api = iterm2
        return self._api

    async def step(self, app, rows, settings, log):
        """Bring the tabs into line with one reading: `rows` are the agent rows after the band, `settings` the
        ones read for this rebuild. `log` takes one line."""
        if not self.adopted:
            self.adopted = True
            await self.adopt(app, log)
        want = wanted(rows, settings)
        for sid in sorted(self.have.keys() - want.keys()):
            held = self.have.pop(sid)
            if isinstance(held, Painted):
                await self.release(app, sid, held, log)
        for sid, name in sorted(want.items()):
            held = self.have.get(sid)
            if held is None or held.name != name:
                await self.paint(app, sid, name, held, log)

    async def adopt(self, app, log):
        """Read every pane once: a paint a daemon that died left enters `have`, so the first plan keeps it,
        repaints it or puts it back, and a restart neither flickers nor takes it for the pane's own."""
        for session in [session for window in app.terminal_windows for tab in window.tabs for session in tab.sessions]:
            colours = await self.read(session, log)
            found = recognise(colours) if colours else None
            if found:
                self.have[session.session_id] = found
                log(f"tab colour adopted {session.session_id[:8]} {found.name}")

    async def paint(self, app, sid, name, held, log):
        """Paint the tab for `name`. A repaint keeps what the first paint replaced, so the colour that goes
        back is the profile's own, never a paint. A tab that no longer shows the paint (recoloured or switched
        off from its menu, its profile swapped) is its owner's while its card lasts, and is said once."""
        self.have.pop(sid, None)
        session = app.get_session_by_id(sid)
        if session is None:
            return
        tab = await self.read(session, log)
        if tab is None:
            self.have[sid] = Left(name, "failed")
            return
        if isinstance(held, Painted) and not still_ours(tab, held):
            log(f"tab colour recoloured {sid[:8]}")
            self.have[sid] = Left(name, "recoloured")
            return
        kept = {variant: layer.kept for variant, layer in held.layers.items()} if isinstance(held, Painted) else {}
        painted = decide(tab, name, kept)
        if isinstance(painted, Left):
            log(f"tab colour {painted.why} {sid[:8]}")
            self.have[sid] = painted
            return
        fields = {}
        for variant, layer in painted.layers.items():
            tab_field, use_field, _ = VARIANTS[variant]
            fields[tab_field], fields[use_field] = self.api.Color(*layer.wrote), True
        self.have[sid] = painted if await self.write(session, fields, log) else Left(name, "failed")

    async def release(self, app, sid, painted, log):
        """Put back what the paint replaced, while the tab still shows it: every switch it turned on goes off,
        since only a variant that showed no colour of its own is painted, and every colour the profile had
        goes back. One it never had stays as the paint left it, unseen while its switch is off: iTerm2 refuses
        None as a colour."""
        session = app.get_session_by_id(sid)
        if session is None:
            return
        tab = await self.read(session, log)
        if tab is None:
            return
        if not still_ours(tab, painted):
            log(f"tab colour recoloured {sid[:8]}")
            return
        fields = {}
        for variant, layer in painted.layers.items():
            tab_field, use_field, _ = VARIANTS[variant]
            fields[use_field] = False
            if layer.kept is not None:
                fields[tab_field] = layer.kept
        await self.write(session, fields, log)

    async def read(self, session, log):
        """-> the pane's tab colour fields, or None when iTerm2 could not say or the iterm2 package could not
        read what it said (a Dynamic Profile can hold null for a colour), which is logged."""
        try:
            return read_tab(await session.async_get_profile())
        except Exception as error:  # noqa: BLE001 -- an iTerm2 call and the reading of its answer; the rebuild goes on
            log(f"tab colour {session.session_id[:8]}: {error!r}")
            return None

    async def write(self, session, fields, log):
        """Set `fields`, profile field -> value, through the session's own profile, so the saved one never
        changes. -> whether iTerm2 took them; a refusal is logged."""
        local = self.api.LocalWriteOnlyProfile()
        for field, value in fields.items():
            getattr(local, "set_" + field)(value)
        try:
            await session.async_set_profile_properties(local)
        except Exception as error:  # noqa: BLE001 -- an iTerm2 call; the rebuild goes on
            log(f"tab colour {session.session_id[:8]}: {error!r}")
            return False
        return True
