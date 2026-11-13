"""Checks the campaign runner (issue #68) without booting guests: re-validation at launch,
the retry rule, the funnel and the rejected-cases table."""

import json

import pytest

from explorer import campaign, planner
from explorer.cache import Cache, CachedOutcome


@pytest.fixture(scope="module")
def space():
    return planner.Space()


@pytest.fixture(scope="module")
def plan(space):
    return planner.plan(seed=0, space=space)


def _runner(script):
    """A fake run_cached: returns the next status from ``script`` for each call."""
    calls = []

    def run(candidate, cache, *, context, **kwargs):
        calls.append(context)
        status = script.pop(0) if script else "ACCEPTED"
        hit = status == "HIT"
        status = "ACCEPTED" if hit else status
        outcome = CachedOutcome(key="k", run_id=f"r{len(calls)}", status=status,
                                reason=None if status == "ACCEPTED" else "why",
                                signature={"fact": 1}, run_dir=None, timeout_s=600,
                                context=context, recorded_at="t", independent=not hit)
        return outcome, (None if hit else object())
    return run, calls


@pytest.fixture
def db(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    yield c
    c.close()


def test_every_planned_candidate_runs_once_when_accepted(plan, db, tmp_path):
    runner, calls = _runner([])
    results = campaign.run(plan, "t", cache=db, campaigns_dir=tmp_path, runner=runner)
    assert [r["status"] for r in results["results"]] == ["ACCEPTED"] * len(plan["candidates"])
    assert len(calls) == len(plan["candidates"])
    assert all(c["campaign"] == "t" and c["seed"] == 0 for c in calls)


@pytest.mark.parametrize("first", ["SETUP_FAIL", "TIMEOUT"])
def test_setup_fail_and_timeout_are_rerun_once(plan, db, tmp_path, first):
    one = {**plan, "candidates": plan["candidates"][:1]}
    runner, calls = _runner([first, first])
    results = campaign.run(one, "t", cache=db, campaigns_dir=tmp_path, runner=runner)
    entry = results["results"][0]
    assert [a["status"] for a in entry["attempts"]] == [first, first]
    assert entry["status"] == first and [c["attempt"] for c in calls] == [1, 2]


def test_rejected_is_a_result_not_retried(plan, db, tmp_path):
    one = {**plan, "candidates": plan["candidates"][:1]}
    runner, calls = _runner(["REJECTED"])
    entry = campaign.run(one, "t", cache=db, campaigns_dir=tmp_path, runner=runner)["results"][0]
    assert entry["status"] == "REJECTED" and len(calls) == 1


def test_a_candidate_todays_rules_reject_isnt_launched(plan, db, tmp_path):
    bad = json.loads(json.dumps(plan["candidates"][0]))
    bad["candidate"]["config"]["ap"]["beacon_protection"] = False
    runner, calls = _runner([])
    entry = campaign.run({**plan, "candidates": [bad]}, "t", cache=db, campaigns_dir=tmp_path,
                         runner=runner)["results"][0]
    assert entry["status"] == "NOT_RUN_P1" and "SEC.EHT_BEACON_PROT" in entry["reason"]
    assert calls == []


def test_funnel_adds_up(plan, space, db, tmp_path):
    runner, _ = _runner(["REJECTED", "SETUP_FAIL", "ACCEPTED", "HIT"])
    results = campaign.run(plan, "t", cache=db, campaigns_dir=tmp_path, runner=runner)
    counts = campaign.pruning_counts(plan, results)
    assert counts["enumerated"] == len(space.assessments)
    assert counts["P1"]["passes_modeled_rules"] + counts["P1"]["spec_rule_violation"] \
        + counts["P1"]["spec_undetermined_review_queue"] == counts["P0"]["well_formed"]
    assert sum(counts["P3"].values()) == counts["planned"]["candidates"]
    assert counts["P3"]["REJECTED"] == 1 and counts["executed"]["retries"] == 1
    assert counts["executed"]["cache_hits"] == 1
    assert counts["executed"]["guest_boots"] == len(plan["candidates"])  # +1 retry -1 hit
    assert counts["guest_boots_avoided_by_pruning"] == counts["enumerated"] - counts["P2"]["executable"]


def test_rejected_cases_name_rules_and_reasons(plan, space, db, tmp_path):
    runner, _ = _runner(["REJECTED"])
    results = campaign.run(plan, "t", cache=db, campaigns_dir=tmp_path, runner=runner)
    rows = campaign.rejected_cases(plan, results, space)
    p1 = [r for r in rows if r["stage"] == "P1"]
    assert sum(r["count"] for r in p1) == plan["funnel"]["p1"]["SPEC_RULE_VIOLATION"]
    assert all(r["rule_ids"] for r in p1)
    p3 = [r for r in rows if r["stage"] == "P3"]
    assert len(p3) == 1 and p3[0]["outcome"] == "REJECTED" and p3[0]["reason"] == "why"


def test_write_creates_the_files(plan, space, db, tmp_path, monkeypatch):
    monkeypatch.setattr(campaign, "PRUNING_COUNTS", tmp_path / "pruning_counts.json")
    runner, _ = _runner([])
    results = campaign.run(plan, "t", cache=db, campaigns_dir=tmp_path, runner=runner)
    campaign.write(tmp_path / "t", plan, results, campaign.rejected_cases(plan, results, space),
                   campaign.pruning_counts(plan, results))
    assert json.loads((tmp_path / "t" / "results.json").read_text())["campaign"] == "t"
    assert (tmp_path / "t" / "rejected_cases.csv").read_text().startswith("stage,outcome,rule_ids")
    assert json.loads((tmp_path / "pruning_counts.json").read_text())["P3"]["ACCEPTED"] == len(
        plan["candidates"])
