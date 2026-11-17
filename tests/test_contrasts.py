"""Accepted-vs-accepted contrasts (issue #71)."""

import json

import pytest

from explorer import contrasts as C
from explorer.signatures import UNKNOWN

ASSOC = {"action": "associate"}
LINK_REMOVE = {"action": "link_remove", "count": 4, "link_id": 1}


def _candidate(ptk=None, actions=(ASSOC,)):
    return {"config": {"ap": {"links": [{"link_id": 0, "akms": ["OWE"]},
                                        {"link_id": 1, "akms": ["OWE"]}],
                              "ptk_rekey_interval_s": ptk},
                       "sta": {"akms": ["OWE"]}},
            "actions": list(actions)}


def _run(run_id, harness="h1", **facts):
    base = {"test_result": "PASS", "disconnects": [], "disconnect_reasons": [],
            "valid_links": "0x3", "ptk_rekeys_completed": 0}
    return C.Run(run_id=run_id, folder=f"nowhere/{run_id}", facts={**base, **facts},
                 harness=harness)


def _group(candidate, *runs):
    return C.Group(candidate=candidate, runs=list(runs), harness=runs[0].harness)


def _any(candidate):
    return True


# --- facts --------------------------------------------------------------------------

def test_disconnect_reasons_ignore_count_and_order():
    one = C.facts({"test": "t", "disconnects": [
        {"reason": 15, "locally_generated": False}, {"reason": 3, "locally_generated": True}]})
    three = C.facts({"test": "t", "disconnects": [
        {"reason": 3, "locally_generated": True}] + [{"reason": 15, "locally_generated": False}] * 3})
    assert one["disconnect_reasons"] == three["disconnect_reasons"] == [[3, True], [15, False]]
    assert "test" not in one


def test_unknown_disconnects_stay_unknown():
    assert C.facts({"test": "t", "disconnects": UNKNOWN})["disconnect_reasons"] == UNKNOWN


# --- inputs -------------------------------------------------------------------------

def test_one_config_value_is_one_input():
    diff = C.input_diff(_candidate(ptk=None), _candidate(ptk=5))
    assert diff == {"config.ap.ptk_rekey_interval_s": [None, 5]}
    assert C.distance(diff) == 1


def test_each_action_step_counts():
    diff = C.input_diff(_candidate(actions=(ASSOC, LINK_REMOVE)), _candidate())
    assert diff == {"actions": [[LINK_REMOVE], []]}
    assert C.distance(diff) == 1
    four_steps = [{"action": "disable_enable_mld", "command": c} for c in "ABCD"]
    swap = C.input_diff(_candidate(actions=(ASSOC, *four_steps)),
                        _candidate(actions=(ASSOC, LINK_REMOVE)))
    assert C.distance(swap) == 5


def test_a_reordering_is_one_input():
    diff = C.input_diff(_candidate(actions=(ASSOC, LINK_REMOVE)),
                        _candidate(actions=(LINK_REMOVE, ASSOC)))
    assert list(diff) == ["actions order"] and C.distance(diff) == 1


def test_per_link_values_are_separate_inputs():
    a, b = _candidate(), _candidate()
    b["config"]["ap"]["links"][1]["akms"] = ["SAE-EXT-KEY"]
    assert C.input_diff(a, b) == {"config.ap.links[1].akms": [["OWE"], ["SAE-EXT-KEY"]]}


# --- what can be claimed --------------------------------------------------------------

def test_claims_only_measured_stable_differences():
    a = _group(_candidate(), _run("1", ptk_rekeys_completed=0, valid_links="0x1"),
               _run("2", ptk_rekeys_completed=0, valid_links="0x3"))
    b = _group(_candidate(ptk=5), _run("3", ptk_rekeys_completed=2, valid_links=UNKNOWN,
                                       disconnects=UNKNOWN))
    diffs, unstable = C.compare(a, b)
    assert [d.fact for d in diffs] == ["ptk_rekeys_completed"]
    assert unstable == ["valid_links"]          # differs between A's repeats
    # disconnects is UNKNOWN on B: not a difference, not unstable either


def test_find_respects_max_inputs_and_needs_a_difference():
    base = _group(_candidate(), _run("1"))
    # Two action steps from base, three from the ptk=5 group.
    far = _candidate(actions=(ASSOC, LINK_REMOVE, {**LINK_REMOVE, "link_id": 0}))
    groups = [base, _group(far, _run("2", ptk_rekeys_completed=1)),
              _group(_candidate(ptk=5), _run("3"))]       # 1 input from base, same facts
    assert C.find(groups, max_inputs=1, supported=_any) == []
    found = C.find(groups, max_inputs=2, supported=_any)
    assert [(c.a_runs, c.b_runs) for c in found] == [(["1"], ["2"])]
    assert not found[0].reproduced


def test_reproduced_needs_three_runs_per_side():
    a = _group(_candidate(), *[_run(str(i)) for i in range(3)])
    b = _group(_candidate(ptk=5), *[_run(str(i), ptk_rekeys_completed=1) for i in (4, 5, 6)])
    (contrast,) = C.find([a, b], supported=_any)
    assert contrast.reproduced
    assert contrast.a_runs == ["0", "1", "2"]


def test_repeats_and_sides_share_a_harness():
    runs = [(_candidate(), _run("1", harness="old")), (_candidate(), _run("2", harness="new")),
            (_candidate(ptk=5), _run("3", harness="old", ptk_rekeys_completed=1))]
    groups = C.group(runs)
    assert [[r.run_id for r in g.runs] for g in groups] == [["1"], ["2"], ["3"]]
    (contrast,) = C.find(groups, supported=_any)       # "2" has no same-harness partner
    assert (contrast.a_runs, contrast.b_runs, contrast.harness) == (["1"], ["3"], "old")
    assert not contrast.current_harness


def test_both_sides_must_be_supported():
    a = _group(_candidate(), _run("1"))
    b = _group(_candidate(ptk=5), _run("2", ptk_rekeys_completed=1))
    assert C.find([a, b], supported=lambda c: c["config"]["ap"]["ptk_rekey_interval_s"]) == []


def test_run_harness_recorded_or_from_the_repo_commit():
    from explorer.cache import harness_digest_at
    recorded = {"explorer_plan": {"explorer": {"cache_key_parts": {"harness": "abc"}}}}
    assert C.run_harness(recorded) == "abc"
    commit = "149f78ed94d54262b01c1cc0634dd8001c286d55"
    clean = {"versions": {"repo_commit": commit, "repo_docker_dir_modified": False}}
    assert C.run_harness(clean) == harness_digest_at(commit) is not None
    assert C.run_harness({"versions": {"repo_commit": commit,
                                       "repo_docker_dir_modified": True}}) is None


# --- the committed runs ------------------------------------------------------------------

@pytest.fixture(scope="module")
def committed():
    return C.accepted_runs()


def test_sides_are_accepted_legal_runs(committed):
    ids = {run.run_id for _, run in committed}
    # The four REJECTED runs of campaigns/seed0-2026-11-13 are never sides.
    rejected = [r["run_id"] for r in json.loads(
        (C.REPO_ROOT / "campaigns/seed0-2026-11-13/results.json").read_text())["results"]
        if r["status"] == "REJECTED"]
    assert len(rejected) == 4 and not ids & set(rejected)
    assert len(ids) == len(committed) >= 33


def test_evidence_points_at_the_log_lines():
    lines = C.evidence("campaigns/seed1-fresh-2026-11-15/1794812777", "disconnects")
    assert lines and all("CTRL-EVENT-DISCONNECTED" in line for line in lines)
    assert any("reason=15" in line for line in lines)
    last = C.evidence("campaigns/seed1-fresh-2026-11-15/1794812777", "station_status")
    assert len(last) == 1 and "station status" in last[0]


def test_committed_contrasts_json_is_current():
    on_disk = json.loads(C.CONTRASTS_JSON.read_text())
    assert on_disk == json.loads(json.dumps(C.build(on_disk["max_inputs"]), sort_keys=True)), (
        "contrasts/contrasts.json is out of date: run scripts/find_contrasts.py")


def test_at_least_two_reproduced_contrasts():
    # Issue #71's "done when": >= 2 contrasts with real run IDs, on today's harness.
    data = json.loads(C.CONTRASTS_JSON.read_text())
    reproduced = [c for c in data["contrasts"] if c["reproduced"] and c["current_harness"]]
    assert len(reproduced) >= 2
    for c in reproduced:
        assert c["facts"] and all(UNKNOWN not in (f["a"], f["b"]) for f in c["facts"])
        assert C.p2_supported(c["candidate_a"]) and C.p2_supported(c["candidate_b"])
