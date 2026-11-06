# ABOUTME: The iTerm2 a pane writer's tests talk to: colours, a session's own profile and the writes made
# ABOUTME: to it, and an app that finds sessions by id, refusing what iTerm2 refuses.


class Colour:
    """iterm2.Color as a profile hands it out: floats from 0 to 255."""
    def __init__(self, red, green, blue, alpha=255):
        self.red, self.green, self.blue, self.alpha = red, green, blue, alpha

    def __eq__(self, other):
        return isinstance(other, Colour) and (other.red, other.green, other.blue, other.alpha) == \
            (self.red, self.green, self.blue, self.alpha)

    def __repr__(self):
        return f"Colour{(self.red, self.green, self.blue, self.alpha)}"


#: The profile fields the pane writers set, as iterm2.LocalWriteOnlyProfile names its setters.
FIELDS = ("badge_text", "badge_color", "badge_color_light", "badge_color_dark",
          "tab_color", "tab_color_light", "tab_color_dark",
          "use_tab_color", "use_tab_color_light", "use_tab_color_dark")


class LocalProfile:
    """What iterm2.LocalWriteOnlyProfile does for a writer: takes the fields and remembers them. A setter it
    lacks is an AttributeError, as on the real one."""
    def __init__(self):
        self.values = {}

    def __getattr__(self, name):
        field = name.removeprefix("set_")
        if name.startswith("set_") and field in FIELDS:
            return lambda value: self.values.__setitem__(field, value)
        raise AttributeError(name)


class Api:
    LocalWriteOnlyProfile = LocalProfile
    Color = Colour


class Session:
    """A pane with its own profile. A write lands on the profile, a colour as the floats iTerm2 reads it back as;
    a colour of None is refused whole, as iTerm2 answers REQUEST_MALFORMED."""
    def __init__(self, sid, profile):
        self.session_id = sid
        self.profile = profile
        self.writes = []
        self.reads = 0

    async def async_get_profile(self):
        self.reads += 1
        return self.profile

    async def async_set_profile_properties(self, local):
        if any(value is None for field, value in local.values.items() if "color" in field):
            raise RuntimeError("REQUEST_MALFORMED")
        self.writes.append(dict(local.values))
        for field, value in local.values.items():
            if isinstance(value, Colour):
                value = Colour(*(c / 255 * 255 for c in (value.red, value.green, value.blue)), value.alpha)
            setattr(self.profile, field, value)


class App:
    def __init__(self, *sessions):
        self.sessions = {s.session_id: s for s in sessions}
        self.terminal_windows = [type("W", (), {"tabs": [type("T", (), {"sessions": list(self.sessions.values())})()]})()]

    def get_session_by_id(self, sid):
        return self.sessions.get(sid)
