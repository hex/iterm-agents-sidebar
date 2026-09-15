"""Reading an account's usage from the real endpoint.

The live test sends a token that was never issued, which the endpoint refuses
without counting against any account.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import request_usage, usage_outcome

READING = '{"five_hour": {"utilization": 19.0, "resets_at": "2026-09-15T12:00:00+00:00"}}'


def test_usage_outcome_reads_a_successful_reply():
    outcome, usage = usage_outcome(200, READING)
    assert outcome == "ok"
    assert usage["five_hour"] == {"used": 19.0, "resets_at": 1789473600}


@pytest.mark.parametrize("status, body, outcome", [
    (200, "<html>maintenance</html>", "failed"),
    (200, "[1, 2]", "failed"),
    (401, '{"error": "unauthorized"}', "unauthorized"),
    (403, "", "failed"),
    (429, "", "rate_limited"),
    (503, READING, "failed"),
])
def test_usage_outcome_names_every_other_reply(status, body, outcome):
    assert usage_outcome(status, body) == (outcome, None)


@pytest.mark.skipif(sys.platform != "darwin", reason="live network test")
def test_the_real_usage_endpoint_refuses_a_token_that_was_never_issued():
    """401 at first; after a few runs in a row the endpoint answers 429 to the
    same bogus token instead. Either proves the request reached it over TLS and
    was classified, and neither is ever read as a usage figure."""
    assert request_usage("agents-sidebar-test-never-issued") in (("unauthorized", None),
                                                                ("rate_limited", None))
