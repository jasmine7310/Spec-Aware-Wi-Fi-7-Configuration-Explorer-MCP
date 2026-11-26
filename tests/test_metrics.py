"""metrics.json (#115): generated, current, and consistent with the files it reads."""

import json

import pytest

from explorer import metrics


@pytest.fixture(scope="module")
def built():
    return metrics.build(timing=False)


@pytest.fixture(scope="module")
def committed():
    return json.loads(metrics.METRICS_JSON.read_text())


def test_committed_metrics_json_is_current(built, committed):
    # The timing block is measured, so it's left out; everything else is from committed files.
    assert metrics.untimed(committed) == json.loads(json.dumps(built)), (
        "metrics.json is out of date: run scripts/build_metrics.py")


def test_timing_block_is_present_and_plausible(committed):
    timing = committed["timing"]
    assert set(timing["mean_ms_per_assignment"]) == {"p0", "configspace", "p1", "p2"}
    assert all(ms > 0 for ms in timing["mean_ms_per_assignment"].values())
    # A check is far cheaper than a guest boot: that's the point of pruning first.
    assert timing["checks_per_guest_boot"] > 100
    # Machine-dependent, so it says which machine it was measured on.
    assert timing["machine"]["platform"] and timing["machine"]["python"]
    stages = timing["mean_ms_per_assignment"]
    assert timing["ms_per_assignment_reaching_p2"] == pytest.approx(sum(stages.values()),
                                                                    abs=0.005)
    # P2 runs only for the assignments P1 passes, so the mean over the space is lower.
    assert timing["ms_per_assignment_over_space"] < timing["ms_per_assignment_reaching_p2"]


def test_space_funnel_adds_up(built):
    space = built["space"]
    avoided = space["guest_boots_avoided"]
    assert avoided["by_p0"] + avoided["by_p1"] + avoided["by_p2"] == avoided["total"]
    assert space["enumerated"] - avoided["total"] == space["p2"]["executable"]
    assert space["p2"]["executable"] == space["p2"]["supported"] + space["p2"]["probe"]
    p1 = space["p1"]
    assert (p1["passes_modeled_rules"] + p1["spec_rule_violation"] + p1["spec_undetermined"]
            == space["p0_well_formed"])


def test_space_matches_the_committed_plan_funnel(built):
    plan = json.loads((metrics.REPO_ROOT / "campaign_plan.json").read_text())["funnel"]
    space = built["space"]
    assert space["enumerated"] == plan["enumerated"]
    assert space["p2"]["executable"] == plan["executable"]
    assert space["p1"]["rejections_by_rule"] == plan["p1_rejections_by_rule"]


def test_no_p1_estimate_is_an_estimate(built):
    est = built["no_p1_estimate"]
    space = built["space"]
    share = space["p1"]["spec_rule_violation"] / space["p0_well_formed"]
    assert est["p1_rejected_share"] == round(share, 4)
    assert est["expected_wasted_boots"] == round(est["budget"] * share, 2)
    assert sum(v for k, v in est["sample"].items() if k not in ("seed", "picks")) \
        == est["sample"]["picks"] == est["budget"]
    assert "not runs" in est["note"]


def test_campaign_numbers_match_their_files(built):
    for c in built["campaigns"]:
        folder = metrics.REPO_ROOT / "campaigns" / c["id"]
        counts = json.loads((folder / "pruning_counts.json").read_text())
        assert c["p3"] == counts["P3"]
        assert c["guest_boots"] == counts["executed"]["guest_boots"]
        assert c["distinct_signatures"] <= c["accepted_runs"] <= c["p3"]["ACCEPTED"]
        echo = c["station_status_echo"]
        assert echo["distinct_signatures_without_it"] <= c["distinct_signatures"]
        assert echo["pairs_differing_only_in_it"] <= c["contrasts"]["any_distance"]
    assert "station_status" in built["campaigns_note"]


def test_held_out_waits_for_a_fresh_campaign_on_the_frozen_model(built):
    fresh = [c for c in built["campaigns"] if c["mode"]["fresh"]]
    freeze = built["held_out"]["freeze"]
    if built["held_out"]["campaign"] is None:
        assert not fresh or freeze is None or freeze["differences_now"] or all(
            c["model_digest"] != freeze["model_digest"] or c["started_at"] < freeze["frozen_at"]
            for c in fresh)
    else:
        assert built["held_out"]["campaign"] in {c["id"] for c in fresh}


def _campaign(name, started_at, fresh=True, digest="m1"):
    return {"id": name, "started_at": started_at, "model_digest": digest,
            "mode": {"build_on_runs": False, "fresh": fresh}}


@pytest.mark.parametrize("campaigns, differences, expected", [
    # A fresh campaign on the frozen model, started after the freeze.
    ([_campaign("after", "2026-12-02T10:00:00Z")], [], "after"),
    # A trial started before the freeze doesn't count.
    ([_campaign("trial", "2026-11-30T10:00:00Z")], [], None),
    ([_campaign("trial", "2026-11-30T10:00:00Z"), _campaign("after", "2026-12-02T10:00:00Z")],
     [], "after"),
    # Not fresh, or on another model.
    ([_campaign("cached", "2026-12-02T10:00:00Z", fresh=False)], [], None),
    ([_campaign("other", "2026-12-02T10:00:00Z", digest="m2")], [], None),
    # Something frozen changed since the freeze.
    ([_campaign("after", "2026-12-02T10:00:00Z")], ["rules_sha256"], None),
])
def test_held_out_needs_a_fresh_campaign_after_an_unchanged_freeze(
        tmp_path, monkeypatch, campaigns, differences, expected):
    from explorer import freeze
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps({"tag": "t", "model_digest": "m1",
                                "frozen_at": "2026-12-01T00:00:00Z"}))
    monkeypatch.setattr(freeze, "FREEZE_JSON", path)
    monkeypatch.setattr(freeze, "differences", lambda frozen: differences)
    assert metrics._held_out(campaigns)["campaign"] == expected


def test_counterexamples_catch_every_invalid_case_and_prune_no_permitted_one(built):
    suite = built["counterexamples"]
    assert suite["roadmap_cases"] == 5
    assert suite["invalid_caught_at_expected_stage"] == suite["invalid_cases"]
    assert suite["permitted_cases"] >= 1 and suite["permitted_wrongly_pruned"] == []
    assert suite["mismatches"] == {}


def test_audit_counts_match_the_registry_and_validation(built):
    from explorer.rules import load_rules
    registry = load_rules()
    audit = built["audit"]
    assert audit["rules_and_open_questions"] == len(registry.rules) + len(registry.undetermined)
    validation = json.loads((metrics.REPO_ROOT / "rules" / "validation.json").read_text())
    expected = {"broken_in_a_run": "broken", "cited_runs_only": "cited", "none": "none"}
    assert audit["validation"] == {expected[k]: v for k, v in validation["counts"].items() if v}
    assert audit["findings"] >= 13
    assert set(audit["findings_by_disposition"]) <= set(metrics.DISPOSITIONS)
    possible, by_design = audit["possible_false_prunes"], audit["pruned_by_design"]
    assert len(by_design) == audit["prune_risk"].get("by design", 0)
    assert len(possible) == sum(v for k, v in audit["prune_risk"].items()
                                if k not in ("none", "n/a", "by design"))
    cases = possible + by_design
    assert {c["rule"] for c in cases} <= {r.id for r in registry.rules}
    assert all(c["prune_risk"].startswith("by design") for c in by_design)
    assert all(text for c in cases for text in c["findings"].values())


def test_cache_and_runtime_come_from_the_reductions(built):
    for name, m in built["cache"]["minimizations"].items():
        red = json.loads((metrics.REPO_ROOT / "contrasts" / name / "reduction.json").read_text())
        assert (m["probes"], m["guest_runs"], m["cache_hits"]) == (
            len(red["reduction"]["trace"]), red["reduction"]["guest_runs"],
            red["reduction"]["cache_hits"])
    assert built["runtime"]["campaign_guest_boots"] == sum(
        c["guest_boots"] for c in built["campaigns"])
