"""minimize_contrast over MCP (#74, step 3). A fake guest stands in for Docker; the
stages before it (P0, P1, action order, P2, adapter) are the real ones."""

import asyncio
import json

import pytest
from mcp import Client

from explorer import mcp_server
from explorer.cache import CachedOutcome
from explorer.mcp_server import server

REASON_15 = {"reason": 15, "locally_generated": False}
REASON_3 = {"reason": 3, "locally_generated": True}
# Contrast C1 on today's harness (contrasts/contrasts.json, by its stable ID, #111): A has
# a 5 s PTK rekey with link_remove, B the same without the rekey.
C1 = "x8dc0b42566"
# The 6-input pair from PR #101: A (seed-1 campaign, SAE-EXT-KEY, ptk 5, gtk 5) and B
# (C1's B side, OWE, link 1 indicate_disabled), both with link_remove.
PAIR = ("1794812824", "1794933586")


class FakeGuest:
    """Stands in for cache.run_cached: reason-15 disconnects only with a 5 s PTK rekey and
    link_remove (what C1 shows), served from a dict on a repeat."""

    def __init__(self):
        self.runs, self.stored = [], {}

    def __call__(self, candidate, cache, *, context=None, **kwargs):
        key = json.dumps(candidate.model_dump(mode="json"), sort_keys=True)
        if key in self.stored:
            return self.stored[key].model_copy(update={"independent": False}), None
        self.runs.append(candidate)
        removed = any(s.action == "link_remove" for s in candidate.actions)
        disconnects = ([REASON_15, REASON_3] if candidate.config.ap.ptk_rekey_interval_s == 5
                       and removed else [REASON_3])
        outcome = CachedOutcome(key=key, run_id=str(1800000000 + len(self.runs)),
                                status="ACCEPTED", reason=None,
                                signature={"disconnects": disconnects}, run_dir=None,
                                timeout_s=None, context=context or {}, recorded_at="now")
        self.stored[key] = outcome
        return outcome, object()


@pytest.fixture
def guest(monkeypatch, tmp_path):
    fake = FakeGuest()
    monkeypatch.setattr(mcp_server, "MINIMIZE_RUNNER", fake)
    monkeypatch.setattr(mcp_server, "CACHE_DB", tmp_path / "cache.sqlite")
    monkeypatch.setattr(mcp_server, "stale_harness", lambda: [])
    return fake


def _call(arguments):
    async def go():
        async with Client(server) as client:
            return await client.call_tool("minimize_contrast", arguments)
    return asyncio.run(go())


def _ok(arguments):
    result = _call(arguments)
    assert not result.is_error, result.content[0].text
    return result.structured_content


def _error(arguments):
    result = _call(arguments)
    assert result.is_error
    return result.content[0].text


def test_minimizes_a_committed_contrast(guest):
    report = _ok({"contrast": C1, "facts": ["disconnect_reasons"]})
    # One run per probe: #73's MINIMIZED label needs the 3/3 verify step, which this tool
    # doesn't run (the #74 transcript caught it reporting MINIMIZED on its own).
    assert report["reduction_status"] == "MINIMIZED"
    assert report["label"] == "PENDING_VERIFICATION"
    assert "PENDING_VERIFICATION" in report["note"] and "verify" in report["note"]
    assert report["side_a"]["run_ids"] == ["1794933558", "1794933622", "1794933677"]
    assert report["side_b"]["run_ids"] == ["1794933586", "1794933644", "1794933694"]
    assert report["target"] == {"disconnect_reasons": [[3, True]]}
    [only] = report["deltas"]
    assert report["minimal"] == [only] and "ptk_rekey_interval_s" in only
    assert [p["config_id"] for p in report["probes"]] == ["target", "baseline"]
    assert all(p["run_ids"] for p in report["probes"])
    assert report["guest_runs"] == len(guest.runs) == 2 and report["cache_hits"] == 0
    assert "#73" in report["note"]


def test_minimizes_a_pair_of_runs_several_inputs_apart(guest):
    report = _ok({"run_a": PAIR[0], "run_b": PAIR[1], "facts": ["disconnect_reasons"]})
    assert report["reduction_status"] == "MINIMIZED"
    assert report["label"] == "PENDING_VERIFICATION"
    assert len(report["deltas"]) == 6
    assert [m.split(": ", 1)[1] for m in report["minimal"]] == [
        "config.ap.ptk_rekey_interval_s: 5 -> null"]
    invalid = [p for p in report["probes"] if p["status"] == "INVALID"]
    # Splitting the AKM changes across links and the client breaks a rule; those probes
    # stop at P1 with their rule IDs and never boot.
    assert invalid and all(p["stage"] == "P1" and p["rule_ids"] and not p["run_ids"]
                           for p in invalid)
    assert report["guest_runs"] == len(guest.runs) == sum(bool(p["run_ids"])
                                                           for p in report["probes"])
    assert sum(report["counts"].values()) == len(report["probes"])


def test_a_repeated_call_is_served_from_the_cache(guest):
    first = _ok({"contrast": C1, "facts": ["disconnect_reasons"]})
    second = _ok({"contrast": C1, "facts": ["disconnect_reasons"]})
    assert second["guest_runs"] == 0 and second["cache_hits"] == first["guest_runs"]
    assert all(p["cache_hit"] for p in second["probes"])


def test_the_budget_stops_before_the_next_guest_run(guest):
    report = _ok({"run_a": PAIR[0], "run_b": PAIR[1], "facts": ["disconnect_reasons"],
                  "max_guest_runs": 1})
    assert report["reduction_status"] == "BUDGET_EXHAUSTED" and report["label"] is None
    assert report["guest_runs"] == len(guest.runs) == 1
    assert report["minimal"] == [] and report["minimal_candidate"] is None


def test_default_target_is_every_differing_fact(guest):
    # Without facts, the target is every fact measured on both runs that differs; the note
    # in the tool's description says to prefer behavior facts.
    report = _ok({"run_a": PAIR[0], "run_b": PAIR[1], "max_guest_runs": 2})
    assert "disconnect_reasons" in report["target"] and len(report["target"]) > 1


@pytest.mark.parametrize("arguments, message", [
    ({}, "give either contrast"),
    ({"contrast": C1, "run_a": PAIR[0], "run_b": PAIR[1]}, "give either contrast"),
    ({"run_a": PAIR[0]}, "give both run_a and run_b"),
    ({"contrast": "x0000000000"}, "no contrast 'x0000000000'"),
    ({"contrast": "c1"}, "that's a minimized contrast"),
    ({"run_a": "1", "run_b": PAIR[1]}, "not a committed ACCEPTED"),
    ({"run_a": PAIR[0], "run_b": PAIR[0]}, "differ in no measured fact"),
    ({"contrast": C1, "facts": ["valid_links"]}, "not claimed by this contrast"),
    ({"contrast": C1, "facts": []}, "facts is empty"),
    ({"contrast": C1, "max_guest_runs": 0}, "max_guest_runs must be 1-40"),
    ({"contrast": C1, "max_guest_runs": 41}, "max_guest_runs must be 1-40"),
])
def test_bad_requests_boot_nothing(guest, arguments, message):
    assert message in _error(arguments)
    assert guest.runs == []


def test_a_stale_image_is_refused(guest, monkeypatch):
    monkeypatch.setattr(mcp_server, "stale_harness", lambda: ["test_explorer_candidate.py"])
    assert "rebuild it" in _error({"contrast": C1, "facts": ["disconnect_reasons"]})
    assert guest.runs == []
