"""Contrasts over MCP (#111): list_contrasts, get_contrast and replay_contrast. A fake guest
stands in for Docker in the replay; list and get read the committed files."""

import asyncio
import json

import pytest
from mcp import Client

from explorer import contrasts, mcp_server
from explorer.cache import CachedOutcome
from explorer.mcp_server import server

REASON_15 = {"reason": 15, "locally_generated": False}
REASON_3 = {"reason": 3, "locally_generated": True}
C1_DIR = contrasts.CONTRASTS_DIR / "c1"


class FakeGuest:
    """Stands in for cache.run_cached in a replay: c1's baseline (5 s PTK rekey) gives
    reason-15 disconnects, its minimal side (no rekey) a local reason 3, as committed.
    ``statuses`` overrides the status of the next runs (e.g. a SETUP_FAIL)."""

    def __init__(self, flip=False, statuses=()):
        self.runs, self.forced, self.flip, self.statuses = [], [], flip, list(statuses)

    def __call__(self, candidate, cache, *, context=None, force=False, **kwargs):
        self.runs.append(candidate)
        self.forced.append(force)
        rekey = candidate.config.ap.ptk_rekey_interval_s == 5
        if self.flip:
            rekey = not rekey
        status = self.statuses.pop(0) if self.statuses else "ACCEPTED"
        outcome = CachedOutcome(
            key="k", run_id=str(1800000000 + len(self.runs)), status=status, reason=None,
            signature=({"disconnects": [REASON_15, REASON_15] if rekey else [REASON_3]}
                       if status == "ACCEPTED" else None),
            run_dir=None, timeout_s=None, context=context or {}, recorded_at="now")
        return outcome, object()


@pytest.fixture
def guest(monkeypatch, tmp_path):
    fake = FakeGuest()
    monkeypatch.setattr(mcp_server, "REPLAY_RUNNER", fake)
    monkeypatch.setattr(mcp_server, "CACHE_DB", tmp_path / "cache.sqlite")
    monkeypatch.setattr(mcp_server, "stale_harness", lambda: [])
    return fake


def _call(tool, arguments=None):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, arguments or {})
    return asyncio.run(go())


def _ok(tool, arguments=None):
    result = _call(tool, arguments)
    assert not result.is_error, result.content[0].text
    return result.structured_content


def _error(tool, arguments):
    result = _call(tool, arguments)
    assert result.is_error
    return result.content[0].text


def _listing():
    result = _ok("list_contrasts")
    return {c["id"]: c for c in result["result"]}


# --- stable IDs -------------------------------------------------------------------------

def test_contrast_ids_are_stable_and_unique():
    data = json.loads(contrasts.CONTRASTS_JSON.read_text())["contrasts"]
    ids = [c["id"] for c in data]
    assert len(set(ids)) == len(ids)
    for c in data:
        assert c["id"] == contrasts.contrast_id(c["candidate_a"], c["candidate_b"], c["harness"])


def test_an_extra_repeat_or_a_new_contrast_keeps_the_ids():
    runs = contrasts.accepted_runs()
    groups = contrasts.group(runs)
    before = {c.id: c.a_runs for c in contrasts.find(groups)}
    # Another repeat of the first contrast's A side, and the list rebuilt.
    first = next(iter(before))
    [group] = [g for g in groups if [r.run_id for r in g.runs] == before[first]]
    group.runs.append(group.runs[0].model_copy(update={"run_id": "1899999999"}))
    after = contrasts.find(groups)
    assert {c.id for c in after} == set(before)
    assert "1899999999" in next(c for c in after if c.id == first).a_runs


# --- list and get -----------------------------------------------------------------------

def test_list_contrasts_gives_both_kinds_by_id():
    listing = _listing()
    on_disk = json.loads(contrasts.CONTRASTS_JSON.read_text())["contrasts"]
    assert [i for i, c in listing.items() if c["kind"] == "contrast"] == [c["id"] for c in on_disk]
    c1 = listing["c1"]
    assert c1["kind"] == "minimized" and c1["label"] == "MINIMIZED" and c1["reproduced"]
    assert c1["minimal"] == ["config.ap.ptk_rekey_interval_s: 5 -> null"]
    assert c1["facts"] == ["disconnect_reasons"]


def test_get_contrast_gives_runs_facts_and_log_lines():
    cid = json.loads(contrasts.CONTRASTS_JSON.read_text())["contrasts"][0]["id"]
    details = _ok("get_contrast", {"contrast_id": cid})
    entry = details["contrast"]
    assert details["kind"] == "contrast" and details["minimized"] is None
    for run in entry["a_runs"] + entry["b_runs"]:
        assert run["folder"] and (contrasts.REPO_ROOT / run["folder"] / "manifest.json").is_file()
    assert entry["facts"]
    for fact in entry["facts"]:
        assert fact["a"] != fact["b"]
        for line in fact["evidence_a"] + fact["evidence_b"]:
            path, number, _ = line.split(":", 2)
            assert (contrasts.REPO_ROOT / path).is_file() and int(number) > 0


def test_get_minimized_contrast_gives_the_trace_and_the_verification():
    stored = json.loads((C1_DIR / "reduction.json").read_text())
    details = _ok("get_contrast", {"contrast_id": "c1"})
    entry = details["minimized"]
    assert details["kind"] == "minimized" and details["contrast"] is None
    assert entry["label"] == "MINIMIZED" and entry["folder"] == "contrasts/c1"
    assert entry["readme"] == "contrasts/c1/README.md"
    assert entry["target"] == {"disconnect_reasons": [[3, True]]}
    assert entry["minimal"] == ["config.ap.ptk_rekey_interval_s: 5 -> null"]
    assert len(entry["probes"]) == len(stored["reduction"]["trace"])
    assert [r["run_id"] for r in entry["a_runs"]] == stored["contrast"]["a_runs"]
    for side, expected in (("baseline_runs", False), ("minimal_runs", True)):
        runs = entry[side]
        assert len(runs) == 3
        for run in runs:
            assert run["status"] == "ACCEPTED" and run["matches_target"] is expected
            assert run["folder"] == f"contrasts/runs/{run['run_id']}"
            assert run["evidence"] and all("CTRL-EVENT-DISCONNECTED" in e for e in run["evidence"])


def test_unknown_contrast():
    assert "no contrast 'c9'" in _error("get_contrast", {"contrast_id": "c9"})


# --- replay -----------------------------------------------------------------------------

def test_replay_reruns_both_sides_fresh(guest):
    before = (C1_DIR / "reduction.json").read_bytes()
    report = _ok("replay_contrast", {"contrast_id": "c1"})
    assert report["replay"] == "REPRODUCED" and report["committed_label"] == "MINIMIZED"
    assert report["same_facts_as_committed"] is True
    assert len(report["baseline_runs"]) == len(report["minimal_runs"]) == 3
    assert all(r["matches_target"] is False for r in report["baseline_runs"])
    assert all(r["matches_target"] is True for r in report["minimal_runs"])
    # Six fresh guests, every one forced: never a cache hit.
    assert report["guest_runs"] == len(guest.runs) == 6 and report["cache_hits"] == 0
    assert all(guest.forced)
    assert (C1_DIR / "reduction.json").read_bytes() == before


def test_replay_that_doesnt_reproduce_says_so(guest):
    guest.flip = True
    report = _ok("replay_contrast", {"contrast_id": "c1", "runs": 1})
    assert report["replay"] == "NOT_REPRODUCED"
    assert report["committed_label"] == "MINIMIZED"
    assert report["same_facts_as_committed"] is False
    assert "unchanged" in report["note"]


def test_a_setup_fail_is_rerun_once_within_the_budget(guest):
    guest.statuses = ["SETUP_FAIL"]
    report = _ok("replay_contrast", {"contrast_id": "c1", "runs": 1})
    assert [r["status"] for r in report["baseline_runs"]] == ["SETUP_FAIL", "ACCEPTED"]
    assert report["replay"] == "REPRODUCED" and report["guest_runs"] == 3


def test_a_setup_fail_without_retries_doesnt_reproduce(guest):
    guest.statuses = ["SETUP_FAIL"]
    report = _ok("replay_contrast", {"contrast_id": "c1", "runs": 1, "retries": 0})
    assert report["replay"] == "NOT_REPRODUCED" and report["guest_runs"] == 2


@pytest.mark.parametrize("arguments, message", [
    ({"contrast_id": "x8dc0b42566"}, "not minimized yet"),
    ({"contrast_id": "c9"}, "no minimized contrast 'c9'"),
    ({"contrast_id": "c1", "runs": 0}, "runs must be 1-3"),
    ({"contrast_id": "c1", "runs": 4}, "runs must be 1-3"),
    ({"contrast_id": "c1", "retries": 2}, "retries must be 0 or 1"),
])
def test_bad_replays_boot_nothing(guest, arguments, message):
    assert message in _error("replay_contrast", arguments)
    assert guest.runs == []


def test_the_budget_never_exceeds_the_cap():
    assert 2 * 3 * (1 + 1) <= mcp_server.MAX_REPLAY_RUNS


def test_a_stale_image_is_refused(guest, monkeypatch):
    monkeypatch.setattr(mcp_server, "stale_harness", lambda: ["test_explorer_candidate.py"])
    assert "rebuild it" in _error("replay_contrast", {"contrast_id": "c1"})
    assert guest.runs == []
