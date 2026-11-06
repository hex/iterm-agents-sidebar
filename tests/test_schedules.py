# ABOUTME: Tests for schedules.py: when a five-field cron expression next runs, and the words a card says it in.
# ABOUTME: Epochs are UTC literals worked out with date(1), never recomputed the way the code does.
from datetime import datetime, timedelta, timezone

import pytest

import schedules

UTC = timezone.utc
#: Thursday 5 November 2026, 13:21:30 UTC.
THU_1321 = 1793884890


@pytest.mark.parametrize("expression, after, expected", [
    # The first matching minute after `after`, never `after` itself.
    ("*/10 * * * *", THU_1321, 1793885400),
    ("*/10 * * * *", 1793885400, 1793886000),
    # A daily one past its minute waits for tomorrow's.
    ("31 13 * * *", 1793885465, 1793971860),
    # A pinned date this year, or the same date next year once it has gone by.
    ("26 13 5 11 *", 1793884860, 1793885160),
    ("26 13 5 11 *", 1793885220, 1825421160),
    # Lists and ranges: Friday 17:45 waits for Monday's first half hour.
    ("0,30 9-17 * * 1-5", 1793987100, 1794214800),
    # A stepped range starts at its own low end.
    ("10-50/20 * * * *", 1793883600, 1793884200),
    ("10-50/20 * * * *", 1793886600, 1793887800),
    # Day of month and day of week both restricted: either one will do.
    ("0 9 9 * 5", 1793959200, 1794214800),
    ("0 9 9 * 5", 1793872800, 1793955600),
    # A day of month that starts with * leaves the weekday alone, as cron
    # reads it: odd days that are Mondays, not odd days or Mondays.
    ("0 9 */2 * 1", 1793872800, 1794214800),
    # Sunday is 0 and 7.
    ("0 9 * * 0", 1793872800, 1794128400),
    ("0 9 * * 7", 1793872800, 1794128400),
    ("0 9 * * 5-7", 1793959200, 1794042000),
    # The month field.
    ("0 0 1 1 *", THU_1321, 1798761600),
    # The search starts on the zone's own date: 23:30 UTC is already the 6th east of it.
    ("45 23 * * *", 1793921400, 1793922300),
    # Fields split on any run of whitespace.
    ("  31\t13 *  * * ", 1793885465, 1793971860),
])
def test_next_run_is_the_first_matching_minute_after(expression, after, expected):
    assert schedules.next_run(expression, after, tz=UTC) == expected


def test_an_expression_that_never_matches_within_400_days_has_no_next_run():
    assert schedules.next_run("0 0 30 2 *", THU_1321, tz=UTC) is None
    # 29 February 2028 is 846 days out.
    assert schedules.next_run("0 0 29 2 *", THU_1321, tz=UTC) is None


@pytest.mark.parametrize("expression", [
    "", "every 5m", "* * * *", "* * * * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * 32 * *",
    "* * * 0 *", "* * * 13 *", "* * * * 8", "*/0 * * * *", "5-1 * * * *", "1,,2 * * * *", "1- * * * *",
    "-1 * * * *", "*/ * * * *", "1/5 * * * *", "MON * * * *", "* * * * MON", "@daily", "1.5 * * * *",
])
def test_an_expression_it_cannot_read_has_no_next_run(expression):
    assert schedules.next_run(expression, THU_1321, tz=UTC) is None


def test_with_no_zone_given_the_fields_are_local_time():
    after = datetime(2026, 11, 5, 13, 21).timestamp()
    assert schedules.next_run("31 13 * * *", after) == datetime(2026, 11, 5, 13, 31).timestamp()


def said(schedule, recurring, upcoming, **due):
    return schedules.said({"id": "6ba43431", "schedule": schedule, "recurring": recurring, "prompt": "say hello",
                           "next": upcoming, **due}, THU_1321, tz=UTC)


@pytest.mark.parametrize("schedule, upcoming, words", [
    ("*/10 * * * *", 1793885400, "every 10 min"),
    ("*/1 * * * *", 1793884920, "every 1 min"),
    ("0 */2 * * *", 1793887200, "every 2 h"),
    ("30 */2 * * *", 1793889000, "every 2 h at :30"),
    ("5 */3 * * *", 1793891100, "every 3 h at :05"),
    ("0 9 * * *", 1793955600, "daily at 09:00"),
    # A step as wide as its field runs once per hour or day, not every 90 minutes.
    ("*/90 * * * *", 1793887200, "next 14:00"),
    ("0 */24 * * *", 1793923200, "next Fri 00:00"),
    ("0,30 * * * *", 1793885400, "next 13:30"),
    ("0 * * * *", 1793887200, "next 14:00"),
    ("0 9 * * 3", 1794387600, "next Wed 09:00"),
    # A week out is a date: "Thu" would read as today.
    ("0 9 * * 4", 1794474000, "next 12 Nov 09:00"),
    ("0 0 1 * *", 1796083200, "next 1 Dec 00:00"),
])
def test_a_recurring_prompt_says_how_often_or_when_next(schedule, upcoming, words):
    assert said(schedule, True, upcoming) == words


@pytest.mark.parametrize("schedule, upcoming, words", [
    ("31 13 * * *", 1793885460, "once at 13:31"),
    ("31 13 * * *", 1793971860, "once Fri 13:31"),
    ("26 13 5 11 *", 1825421160, "once 5 Nov 13:26"),
    # A one-shot is never "every": the same expression recurring is.
    ("*/10 * * * *", 1793885400, "once at 13:30"),
])
def test_a_one_shot_says_when_it_runs(schedule, upcoming, words):
    assert said(schedule, False, upcoming) == words


def test_a_one_shot_past_its_run_is_due():
    assert said("11 13 * * *", False, 1793884260, due=True) == "due"


def test_today_is_the_day_on_the_clock_the_words_are_read_in():
    """13:21 UTC is 23:21 the evening before at UTC-14."""
    behind = timezone(timedelta(hours=-14))
    entry = {"id": "20c147b9", "schedule": "31 13 * * *", "recurring": False, "prompt": "wake me", "next": 1793885460}
    assert schedules.said(entry, THU_1321, tz=behind) == "once at 23:31"


def test_an_expression_with_no_next_run_is_said_as_written():
    assert said("0 0 30 2 *", True, None) == "0 0 30 2 *"
    assert said("every 5m", False, None) == "every 5m"
