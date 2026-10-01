"""An agent that publishes no clocks (omp: its title is its only word) gets
them from the daemon's own watch of its state, so the attention order can
hold and rank its cards like any other."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import observed_clocks

OMP = {"session_id": "o1", "agent_state": "idle", "working_since": None,
       "idle_since": None, "turn_started": None}


def test_a_session_first_seen_is_stamped_now():
    seen, [row] = observed_clocks({}, [dict(OMP)], 1000)
    assert (row["idle_since"], row["working_since"], row["turn_started"]) == (1000, None, None)
    assert seen == {"o1": ("idle", None, 1000)}


def test_a_state_that_holds_keeps_its_stamp():
    seen, [row] = observed_clocks({"o1": ("idle", 1000, 1000)}, [dict(OMP)], 1090)
    assert row["idle_since"] == 1000 and seen == {"o1": ("idle", 1000, 1000)}


def test_a_turn_starts_its_clocks_and_keeps_the_rest_it_came_from():
    seen, [row] = observed_clocks({"o1": ("idle", 1000, 1000)}, [dict(OMP, agent_state="working")], 1200)
    assert (row["working_since"], row["turn_started"], row["idle_since"]) == (1200, 1200, 1000)
    seen, [row] = observed_clocks(seen, [dict(OMP, agent_state="blocked")], 1300)
    assert (row["working_since"], row["turn_started"], row["idle_since"]) == (None, 1200, 1000)
    seen, [row] = observed_clocks(seen, [dict(OMP, agent_state="idle")], 1400)
    assert (row["working_since"], row["turn_started"], row["idle_since"]) == (None, 1200, 1400)


def test_a_session_with_clocks_of_its_own_is_left_alone():
    claude = {"session_id": "c1", "agent_state": "idle", "working_since": None,
              "idle_since": 900, "turn_started": 800}
    seen, [row] = observed_clocks({}, [claude], 1000)
    assert row["idle_since"] == 900 and seen == {}


def test_a_session_gone_is_forgotten():
    seen, rows = observed_clocks({"o1": ("idle", 1000, 1000)}, [], 1100)
    assert seen == {} and rows == []
