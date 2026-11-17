"""why_pruned and permitted_alternatives (issue #74): the first two steps of the agent
chain, as explorer.pruning computes them and as the MCP tools return them."""

import asyncio
import copy

import pytest
from mcp import Client

from explorer import model_json, planner, pruning
from explorer.mcp_server import server
from explorer.model import Candidate

BASE = model_json.base_candidate()        # F02: SAE-EXT-KEY on both links and the client


def _with(**changes):
    """The F02 base with some dimensions set by model.json label."""
    return model_json.apply(changes)


def _no_common_akm():
    # The roadmap's example: the AP MLD's links advertise no common AKM.
    candidate = copy.deepcopy(BASE)
    candidate["config"]["ap"]["links"][1]["akms"] = ["OWE"]
    return candidate


# --- the campaign space's labels ------------------------------------------------------------


def test_labels_round_trip_on_every_dimension():
    for name, (_, values) in pruning.dimensions().items():
        for label in values:
            assert pruning.current_label(pruning.set_label(BASE, name, label), name) == label


def test_a_label_that_doesnt_fit_is_described():
    assert pruning.current_label(_no_common_akm(), "ap_akm") == (
        'other: [["SAE-EXT-KEY"], ["OWE"]]')


def test_absent_removes_an_action_dimensions_steps():
    with_both = _with(link_remove="present", rekey_gtk_now="present")
    without = pruning.set_label(with_both, "link_remove", "absent")
    assert [s["action"] for s in without["actions"]] == ["associate", "rekey_gtk_now"]


def test_campaign_assignment_only_for_the_spaces_own_candidates():
    choices = {name: values[0] for name, (_, values) in
               ((n, (p, list(v))) for n, (p, v) in pruning.dimensions().items())}
    assert pruning.campaign_assignment(
        Candidate.model_validate(model_json.apply(choices))) == choices
    assert pruning.campaign_assignment(Candidate.model_validate(_no_common_akm())) is None


# --- why pruned ------------------------------------------------------------------------------


def test_a_rule_violation_is_pruned_at_p1_with_its_evidence():
    why = pruning.why_pruned(_no_common_akm())
    assert (why.role, why.stage, why.pruned) == ("pruned", "P1", True)
    findings = {f.rule_id: f for f in why.findings}
    assert set(findings) == {"SEC.MLD_COMMON_SUITES", "SEC.MLD_SAME_RSNXE"}
    common = findings["SEC.MLD_COMMON_SUITES"]
    assert "no common AKM" in common.reason and common.predicate
    assert any(s.doc == "IEEE-802.11be-2024" and s.strength == "shall" and s.page
               for s in common.sources)
    assert common.configspace.startswith("P1 predicate only")
    # #95's labeled experiment broke SEC.MLD_SAME_RSNXE; hostapd accepted it.
    rsnxe = findings["SEC.MLD_SAME_RSNXE"]
    assert rsnxe.validation == "broken_in_a_run"
    assert "runs/experiments/1794875139 (explorer_candidate PASS)" in rsnxe.runs_breaking_it


def test_a_configspace_rule_says_how_it_is_encoded():
    why = pruning.why_pruned(_with(ap_sae_pwe="1"))     # client's sae_pwe unset
    [finding] = why.findings
    assert finding.rule_id == "SEC.SAE_H2E_ONLY_NEEDS_STA_H2E"
    assert finding.configspace.startswith("ConfigSpace ") and "forbidden" in finding.configspace
    assert why.campaign_assignment is not None


def test_an_action_order_rule_is_labeled_not_a_spec_rule():
    candidate = copy.deepcopy(BASE)
    candidate["actions"] = [{"action": "rekey_gtk_now"}]
    why = pruning.why_pruned(candidate)
    assert why.role == "pruned" and [f.rule_id for f in why.findings] == ["AO.ASSOC_REQUIRED"]
    assert why.findings[0].kind == "harness" and "aren't Wi-Fi specification rules" in why.note


def test_an_implementation_limit_is_pruned_at_p2():
    why = pruning.why_pruned(_with(link_remove="present", disable_enable_mld="present"))
    assert (why.role, why.stage, why.findings) == ("unsupported", "P2", [])
    assert why.p2.limit == "P2.DISABLE_MLD_AFTER_LINK_REMOVE" and why.p2.run_ids


def test_a_supported_candidate_isnt_pruned():
    why = pruning.why_pruned(BASE)
    assert (why.role, why.stage, why.pruned) == ("supported", None, False)
    assert why.p2.status == "SUPPORTED" and why.p2.run_ids


def test_a_malformed_candidate_stops_at_p0():
    why = pruning.why_pruned({"config": {}, "actions": []})
    assert (why.role, why.stage) == ("malformed", "P0")
    assert all(f.stage == "P0" and f.sources == [] for f in why.findings)


def test_roles_match_the_planner():
    # why_pruned and the campaign planner agree on every assignment they share.
    space = planner.Space()
    rows = list(space.assessments)[::97]                  # a spread of assignments
    for row in rows:
        assessment = space.assessments[row]
        candidate = model_json.apply(space.choices(row))
        assert pruning.why_pruned(candidate).role == assessment.role, space.choices(row)


# --- permitted alternatives ------------------------------------------------------------------


def test_alternatives_repair_the_roadmaps_example():
    result = pruning.permitted_alternatives(_no_common_akm())
    assert result.original_findings == ["SEC.MLD_COMMON_SUITES", "SEC.MLD_SAME_RSNXE"]
    [best] = result.alternatives
    assert [(c.dimension, c.new) for c in best.changes] == [("ap_akm", "SAE-EXT-KEY")]
    assert best.inputs_changed == {"config.ap.links[1].akms": [["OWE"], ["SAE-EXT-KEY"]]}
    assert best.p2_status == "SUPPORTED" and best.run_ids and best.executable


def test_every_alternative_passes_the_modeled_rules_and_keeps_other_settings():
    original = _with(ap_sae_pwe="1")
    original["config"]["sta"]["sae_groups"] = [20, 19]       # not a dimension: must stay
    result = pruning.permitted_alternatives(original, max_changes=2)
    assert result.alternatives
    for alt in result.alternatives:
        assert pruning.why_pruned(alt.candidate).status == "PASSES_MODELED_RULES"
        assert alt.candidate["config"]["sta"]["sae_groups"] == [20, 19]


def test_alternatives_are_minimal_and_ranked():
    # Client OWE against an AP that offers only SAE-EXT-KEY with H2E only: one change
    # isn't enough (each single fix trips another rule), so every alternative needs two.
    original = _with(sta_akm="OWE", ap_sae_pwe="1")
    one = pruning.permitted_alternatives(original, max_changes=1)
    assert one.alternatives == [] and "larger max_changes" in one.note
    two = pruning.permitted_alternatives(original, max_changes=2, limit=50)
    assert two.alternatives and all(len(a.changes) == 2 for a in two.alternatives)
    sets = [frozenset((c.dimension, c.new) for c in a.changes) for a in two.alternatives]
    assert not any(a < b for a in sets for b in sets)
    ranks = [(not a.executable, a.p2_status != "SUPPORTED") for a in two.alternatives]
    assert [r[1] for r in ranks] == sorted(r[1] for r in ranks)


def test_supersets_of_a_permitted_change_are_skipped():
    result = pruning.permitted_alternatives(_no_common_akm(), max_changes=2, limit=100)
    for alt in result.alternatives:
        changed = {c.dimension: c.new for c in alt.changes}
        assert not (len(changed) == 2 and changed.get("ap_akm") == "SAE-EXT-KEY")


@pytest.mark.parametrize("kwargs, message", [
    ({"max_changes": 0}, "max_changes must be 1-3"),
    ({"max_changes": 4}, "max_changes must be 1-3"),
    ({"limit": 0}, "limit must be at least 1"),
])
def test_bad_arguments(kwargs, message):
    with pytest.raises(ValueError, match=message):
        pruning.permitted_alternatives(BASE, **kwargs)


def test_a_malformed_candidate_has_no_alternatives():
    with pytest.raises(ValueError, match="malformed candidate"):
        pruning.permitted_alternatives({"config": {}, "actions": []})


# --- over MCP --------------------------------------------------------------------------------


def _call(tool, arguments):
    async def go():
        async with Client(server) as client:
            names = [t.name for t in (await client.list_tools()).tools]
            return names, await client.call_tool(tool, arguments)
    return asyncio.run(go())


def test_why_pruned_over_mcp():
    names, result = _call("why_pruned", {"candidate": _no_common_akm()})
    assert {"why_pruned", "permitted_alternatives"} <= set(names)
    assert not result.is_error
    data = result.structured_content
    assert data["role"] == "pruned" and data["stage"] == "P1"
    assert {f["rule_id"] for f in data["findings"]} == {"SEC.MLD_COMMON_SUITES",
                                                         "SEC.MLD_SAME_RSNXE"}


def test_permitted_alternatives_over_mcp():
    _, result = _call("permitted_alternatives", {"candidate": _no_common_akm()})
    assert not result.is_error
    [alt] = result.structured_content["alternatives"]
    assert alt["p2_status"] == "SUPPORTED" and alt["candidate"]["config"]["ap"]["links"][1][
        "akms"] == ["SAE-EXT-KEY"]
    _, bad = _call("permitted_alternatives", {"candidate": BASE, "max_changes": 9})
    assert bad.is_error and "max_changes must be 1-3" in bad.content[0].text
