# ABOUTME: Reads a five-field cron expression and finds when it next matches, in local time,
# ABOUTME: and says a scheduled prompt's next run in the few words its row on a card shows.
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Each field's name and the values it may hold: minute, hour, day of
#: month, month, day of week (Sunday is 0 and 7).
FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 7))
#: How far ahead a run is looked for; past it an expression is as good as never.
SEARCH_DAYS = 400
#: One part of a field: a number, or `*` or a range with an optional step.
PART = re.compile(r"(\*|[0-9]+-[0-9]+)(?:/([0-9]+))?|([0-9]+)")
#: How far ahead a run is still named by its weekday; a week out, the name is today's.
WEEKDAY_NAMED_WITHIN = 6
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
#: Recurring expressions said by how often they run rather than when next.
EVERY_MINUTES = re.compile(r"\*/([0-9]+) \* \* \* \*")
EVERY_HOURS = re.compile(r"([0-9]+) \*/([0-9]+) \* \* \*")
DAILY = re.compile(r"([0-9]+) ([0-9]+) \* \* \*")


@dataclass(frozen=True)
class Schedule:
    """The minutes and hours an expression runs at, in order, and the days,
    months and weekdays it runs on. `any_day` and `any_weekday` say that
    field began with *, which decides how the two day fields combine."""
    minutes: tuple
    hours: tuple
    days: frozenset
    months: frozenset
    weekdays: frozenset
    any_day: bool
    any_weekday: bool

    def runs_on(self, date):
        """Cron's rule: with both day fields restricted either will do; with
        one of them starting with *, both must hold."""
        if date.month not in self.months:
            return False
        on_day = date.day in self.days
        on_weekday = (date.weekday() + 1) % 7 in self.weekdays
        if self.any_day or self.any_weekday:
            return on_day and on_weekday
        return on_day or on_weekday


def field_values(text, name, low, high):
    """One field -> the set of values it allows. Raises ValueError naming the
    field and the text when the field is not `*`, numbers, ranges, steps and
    comma lists of them inside the field's bounds."""
    values = set()
    for part in text.split(","):
        match = PART.fullmatch(part)
        if not match:
            raise ValueError(f"cron {name} field {text!r}: cannot read {part!r}")
        span, step = match.group(1) or match.group(3), int(match.group(2) or 1)
        first, _, last = span.partition("-")
        start, end = (low, high) if span == "*" else (int(first), int(last or first))
        if not low <= start <= end <= high or step < 1:
            raise ValueError(f"cron {name} field {text!r}: {part!r} is outside {low}-{high} or steps by 0")
        values.update(range(start, end + 1, step))
    return values


def parse(expression):
    """A five-field cron expression -> its Schedule. Raises ValueError saying
    which field could not be read."""
    texts = expression.split()
    if len(texts) != len(FIELDS):
        raise ValueError(f"cron expression {expression!r} has {len(texts)} fields, not {len(FIELDS)}")
    minutes, hours, days, months, weekdays = (field_values(text, *field) for text, field in zip(texts, FIELDS))
    return Schedule(tuple(sorted(minutes)), tuple(sorted(hours)), frozenset(days), frozenset(months),
                    frozenset(day % 7 for day in weekdays), texts[2].startswith("*"), texts[4].startswith("*"))


def next_run(expression, after, tz=None):
    """The first minute after `after` (epoch s) that the expression matches,
    as whole epoch seconds; None when it cannot be read or matches nothing in the
    next 400 days. The fields are wall-clock time in `tz`, local time when
    None."""
    try:
        schedule = parse(expression)
    except ValueError:
        return None
    first = datetime.fromtimestamp(after, tz).date()
    for offset in range(SEARCH_DAYS):
        date = first + timedelta(days=offset)
        if not schedule.runs_on(date):
            continue
        for hour in schedule.hours:
            for minute in schedule.minutes:
                # Compared as instants, not wall-clock times: an hour the
                # clocks went back over reads the same minute twice.
                at = int(datetime(date.year, date.month, date.day, hour, minute, tzinfo=tz).timestamp())
                if at > after:
                    return at
    return None


def said(entry, now, tz=None):
    """A published scheduled prompt -> the words for when it runs, as of `now`.

    A recurring prompt with a steady rhythm says it ("every 10 min", "every
    2 h at :30", "daily at 09:00"); any other says its next run ("next
    13:30", "next Wed 09:00", "next 12 Nov 09:00"). A one-shot says when it
    runs ("once at 13:31", "once Fri 13:31") or, past that, "due". One with
    no next run is said as written.
    """
    if entry.get("due"):
        return "due"
    if entry["next"] is None:
        return entry["schedule"]
    if entry["recurring"]:
        rhythm = rhythm_of(" ".join(entry["schedule"].split()))
        if rhythm:
            return rhythm
    at = datetime.fromtimestamp(entry["next"], tz)
    ahead = (at.date() - datetime.fromtimestamp(now, tz).date()).days
    clock = f"{at.hour:02d}:{at.minute:02d}"
    day = ("" if ahead == 0 else WEEKDAYS[at.weekday()] if ahead <= WEEKDAY_NAMED_WITHIN
           else f"{at.day} {MONTHS[at.month - 1]}")
    if entry["recurring"]:
        return f"next {day} {clock}" if day else f"next {clock}"
    return f"once {day} {clock}" if day else f"once at {clock}"


def rhythm_of(expression):
    """How often a recurring expression runs, when that is all it says, or
    None. A step as wide as its field runs once per hour or day, so it says
    no rhythm."""
    if (match := EVERY_MINUTES.fullmatch(expression)) and int(match.group(1)) < 60:
        return f"every {int(match.group(1))} min"
    if (match := EVERY_HOURS.fullmatch(expression)) and int(match.group(2)) < 24:
        minute = int(match.group(1))
        return f"every {int(match.group(2))} h" + (f" at :{minute:02d}" if minute else "")
    if match := DAILY.fullmatch(expression):
        return f"daily at {int(match.group(2)):02d}:{int(match.group(1)):02d}"
    return None
