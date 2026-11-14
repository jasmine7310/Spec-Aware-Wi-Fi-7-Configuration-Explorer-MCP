"""Checks the campaign planner (issue #66): constraint filtering, reproducibility, P2
filtering, the review queue and coverage counting."""

import itertools
import json

import pytest

from explorer import adapter, planner
from explorer.model import Candidate
from explorer.validate import validate_candidate


@pytest.fixture(scope="module")
def space():
    return planner.Space()


@pytest.fixture(scope="module")
def plan0(space):
    # The full design: independent of how much has already run (the committed plan builds on
    # earlier runs and can be empty once every runnable pair is covered).
    return planner.plan(seed=0, space=space, build_on_runs=False)


@pytest.fixture(scope="module")
def next_plan(space):
    return planner.plan(seed=0, space=space)


def _row(space, **choices):
    """A full row: the F02 base labels (first label of each dimension that F02 uses),
    with ``choices`` applied."""
    base = {"ap_akm": "SAE-EXT-KEY", "sta_akm": "SAE-EXT-KEY", "ap_sae_pwe": "unset",
            "sta_sae_pwe": "unset", "ap_pairwise_cipher": "CCMP",
            "ap_link_indicate_disabled": "0", "ap_ptk_rekey_interval": "unset",
            "ap_gtk_rekey_interval": "unset", "rekey_gtk_now": "absent",
            "link_remove": "absent", "disable_enable_mld": "absent"}
    base.update(choices)
    return tuple(base[name] for name in space.names)


def _prefix(space, **choices):
    """The shortest prefix (in dimension order) that sets every dimension in ``choices``;
    dimensions before the last chosen one take F02's labels."""
    row = _row(space, **choices)
    last = max(space.names.index(name) for name in choices)
    return row[:last + 1]


# --- The space and the stages --------------------------------------------------

def test_space_is_every_combination_of_the_admitted_dimensions(space):
    expected = 1
    for labels in space.labels:
        expected *= len(labels)
    assert len(space.assessments) == expected
    assert all(a.candidate is not None for a in space.assessments.values())   # P0


def test_f02_is_legal_and_supported(space):
    a = space.assessments[_row(space)]
    assert (a.p1_status, a.p2_status, a.role) == ("PASSES_MODELED_RULES", "SUPPORTED", "supported")


def test_rule_breaking_rows_are_pruned_with_their_rules(space):
    a = space.assessments[_row(space, ap_sae_pwe="1")]          # client sae_pwe unset
    assert a.role == "pruned" and a.rule_ids == ["SEC.SAE_H2E_ONLY_NEEDS_STA_H2E"]
    b = space.assessments[_row(space, ap_akm="OWE")]            # client still SAE-EXT-KEY
    assert not b.legal and "SEC.MLD_CLIENT_COMMON_AKM" in b.rule_ids


def test_configspace_prunes_what_p1_prunes(space, plan0):
    # The static settings' ConfigSpace verdict matches P1 on every assignment (the actions
    # here never break an AO rule), and the funnel shows it.
    for a in space.assessments.values():
        assert (not a.configspace_rule_ids) == a.legal, a.row
        assert set(a.configspace_rule_ids) <= set(a.rule_ids), a.row
    funnel = plan0["funnel"]
    assert funnel["configspace"]["valid"] == funnel["p1"]["PASSES_MODELED_RULES"]


# --- allpairspy's filter: partial rows ------------------------------------------

def test_filter_keeps_a_partial_row_that_can_still_be_completed(space):
    keep = planner.prefix_filter(space)
    assert keep([])
    assert keep(_prefix(space, ap_akm="OWE"))
    # ap_sae_pwe=1 alone is fine: a later client sae_pwe of 1 or 2 completes it legally,
    # even though the base's unset client wouldn't.
    assert keep(_prefix(space, ap_sae_pwe="1"))


def test_filter_rejects_a_partial_row_no_completion_can_save(space):
    keep = planner.prefix_filter(space)
    assert not keep(_prefix(space, ap_akm="OWE", sta_akm="SAE-EXT-KEY"))
    assert not keep(_prefix(space, ap_sae_pwe="1", sta_sae_pwe="unset"))
    assert not keep(_prefix(space, ap_akm="OWE", ap_sae_pwe="2"))


def test_filter_agrees_with_full_assessments(space):
    keep = planner.prefix_filter(space)
    for row, a in itertools.islice(space.assessments.items(), 0, None, 37):
        assert keep(row) == a.executable, row


# --- The plan ---------------------------------------------------------------------

def test_same_seed_same_plan(space, plan0, next_plan):
    assert planner.plan(seed=0, space=space, build_on_runs=False) == plan0
    assert planner.plan(seed=0, space=space) == next_plan


def test_seed_changes_the_design(space):
    designs = {tuple(r for r, _ in planner.design(space, seed, build_on_runs=False))
               for seed in range(6)}
    assert len(designs) > 1


def test_every_planned_candidate_is_legal_executable_and_runnable(plan0):
    assert plan0["candidates"]
    for c in plan0["candidates"]:
        assert validate_candidate(c["candidate"]).status == "PASSES_MODELED_RULES", c["id"]
        assert c["role"] in ("supported", "probe") and c["p1"] == "PASSES_MODELED_RULES"
        assert adapter.unsupported(Candidate.model_validate(c["candidate"])) == [], c["id"]


def test_planned_candidates_are_distinct(plan0):
    keys = [json.dumps(c["candidate"], sort_keys=True) for c in plan0["candidates"]]
    assert len(keys) == len(set(keys))


def test_plan_and_earlier_runs_cover_every_executable_pair(space, next_plan):
    # Checked from the planned choices, independently of allpairspy: the plan covers
    # exactly what the committed runs (P2 SUPPORTED) left.
    planned = space.pairs_of([tuple(c["choices"][n] for n in space.names)
                              for c in next_plan["candidates"]])
    done = space.pairs_of(space.rows(lambda a: a.role == "supported"))
    assert planned | done >= space.pairs_of(space.rows(lambda a: a.executable))


def test_without_earlier_runs_the_plan_covers_every_executable_pair_itself(space):
    full = planner.plan(seed=0, space=space, build_on_runs=False)
    planned = space.pairs_of([tuple(c["choices"][n] for n in space.names)
                              for c in full["candidates"]])
    assert planned >= space.pairs_of(space.rows(lambda a: a.executable))
    assert full["funnel"]["already_run"] == 0


def test_building_on_runs_plans_only_new_candidates(space, next_plan):
    done = set(space.rows(lambda a: a.role == "supported"))
    assert done and next_plan["funnel"]["already_run"] == len(done)
    assert all(c["role"] == "probe" for c in next_plan["candidates"])
    assert not {tuple(c["choices"][n] for n in space.names) for c in next_plan["candidates"]} & done


def test_unsupported_rows_are_counted_not_planned(space, plan0):
    unsupported = space.rows(lambda a: a.role == "unsupported")
    assert unsupported and plan0["funnel"]["p2"]["unsupported"] == len(unsupported)
    for row in unsupported:
        a = space.assessments[row]
        assert not a.executable and a.p2_limit == "P2.DISABLE_MLD_AFTER_LINK_REMOVE"
        assert space.choices(row)["link_remove"] == space.choices(row)["disable_enable_mld"] == "present"
    assert not any(c["choices"]["link_remove"] == c["choices"]["disable_enable_mld"] == "present"
                   for c in plan0["candidates"])


def test_allpairspy_rows_come_first_then_the_top_up(plan0):
    sources = [c["source"] for c in plan0["candidates"]]
    assert sources[0] == "allpairspy"
    assert sources == sorted(sources, key=lambda s: s != "allpairspy")
    funnel = plan0["funnel"]
    assert funnel["allpairspy_rows"] + funnel["top_up_rows"] == funnel["planned"] + funnel["cut_by_budget"]


def test_budget_cuts_are_reported_not_dropped(space):
    full = planner.plan(seed=0, space=space, build_on_runs=False)
    small = planner.plan(seed=0, budget=5, space=space, build_on_runs=False)
    assert len(small["candidates"]) == 5
    assert small["funnel"]["cut_by_budget"] == len(full["candidates"]) - 5
    assert len(small["cut_by_budget"]) == small["funnel"]["cut_by_budget"]


def test_funnel_adds_up(space, plan0):
    f = plan0["funnel"]
    assert f["enumerated"] == len(space.assessments) == f["p0_well_formed"]
    assert sum(f["p1"].values()) == f["enumerated"]
    assert sum(f["p2"].values()) == f["p1"]["PASSES_MODELED_RULES"]
    assert f["executable"] == f["p2"]["supported"] + f["p2"]["probe"]
    assert plan0["model"]["model_digest"] == space.model["model_digest"]


def test_undetermined_rows_go_to_the_review_queue_not_the_campaign():
    class Pretend(planner.Space):
        # Pretend OWE with link removal were an open question.
        def assess(self, row):
            a = super().assess(row)
            if a.legal and self.choices(row)["ap_akm"] == "OWE" \
                    and self.choices(row)["link_remove"] == "present":
                a.p1_status, a.rule_ids, a.p2_status = "SPEC_UNDETERMINED", ["UND.TEST"], None
            return a
    pretend = Pretend()
    result = planner.plan(seed=0, space=pretend)
    assert result["review_queue"]
    assert all(q["choices"]["ap_akm"] == "OWE" and q["choices"]["link_remove"] == "present"
               for q in result["review_queue"])
    assert not any(c["choices"]["ap_akm"] == "OWE" and c["choices"]["link_remove"] == "present"
                   for c in result["candidates"])
    assert result["funnel"]["p1"]["SPEC_UNDETERMINED"] == len(result["review_queue"])


# --- Coverage ------------------------------------------------------------------------

def test_only_runs_cover_pairs_not_plans(space):
    full = planner.plan(seed=0, space=space, build_on_runs=False)
    plan_rows = [tuple(c["choices"][n] for n in space.names) for c in full["candidates"]]
    nothing_run = planner.coverage(space, plan_rows, ran_rows=[])
    assert nothing_run["modeled_admissible"]["covered_feasible_pairs"] == 0
    assert nothing_run["modeled_admissible"]["pairwise_coverage"] == 0
    assert nothing_run["executable"]["planned_pairwise_coverage"] == 1.0
    assert nothing_run["executable"]["covered_or_planned_pairwise_coverage"] == 1.0
    one = planner.coverage(space, plan_rows, ran_rows=[_row(space)])
    n = len(space.names)
    assert one["modeled_admissible"]["covered_feasible_pairs"] == n * (n - 1) // 2


def test_two_denominators_and_infeasible_pairs_add_up(space):
    cover = planner.coverage(space, [], [])
    p1, p2 = cover["modeled_admissible"], cover["executable"]
    assert p2["feasible_pairs"] <= p1["feasible_pairs"]
    assert p1["feasible_pairs"] + len(cover["infeasible_pairs"]) == cover["all_pairs"]
    assert len(cover["admissible_but_not_executable_pairs"]) == p1["feasible_pairs"] - p2["feasible_pairs"]


def test_a_pair_only_unsupported_assignments_have_names_the_limit(space):
    blocked = planner.coverage(space, [], [])["admissible_but_not_executable_pairs"]
    assert blocked == [{"pair": {"link_remove": "present", "disable_enable_mld": "present"},
                        "p2": {"roles": {"unsupported": 288},
                               "limits": ["P2.DISABLE_MLD_AFTER_LINK_REMOVE"]}}]


def test_infeasible_pairs_name_the_rules_that_rule_them_out(space):
    by_pair = {tuple(sorted(i["pair"].items())): i
               for i in planner.coverage(space, [], [])["infeasible_pairs"]}
    mismatch = by_pair[(("ap_akm", "OWE"), ("sta_akm", "SAE-EXT-KEY"))]
    assert mismatch["rule_ids"] == ["SEC.MLD_CLIENT_COMMON_AKM"]
    assert mismatch["every_assignment_rejected_by_these"]
    h2e_only = by_pair[(("ap_sae_pwe", "1"), ("sta_sae_pwe", "unset"))]
    assert "SEC.SAE_H2E_ONLY_NEEDS_STA_H2E" in h2e_only["rule_ids"]
    assert all(set(i["statuses"]) <= {"SPEC_RULE_VIOLATION", "SPEC_UNDETERMINED", "MALFORMED"}
               for i in by_pair.values())


# --- The committed files ----------------------------------------------------------

def test_committed_plan_matches_its_seed_and_the_current_model(space):
    # Regenerate with: .venv/bin/python scripts/plan_campaign.py --seed <seed>
    committed = json.loads(planner.CAMPAIGN_PLAN.read_text())
    assert committed["model"]["model_digest"] == space.model["model_digest"]
    fresh = planner.plan(seed=committed["seed"], budget=committed["budget"], space=space,
                         build_on_runs=committed["build_on_runs"])
    assert [c["choices"] for c in committed["candidates"]] == [
        c["choices"] for c in fresh["candidates"]]
    cover = json.loads(planner.PAIRWISE_COVERAGE.read_text())
    assert cover["seed"] == committed["seed"] and cover["model_digest"] == space.model["model_digest"]
