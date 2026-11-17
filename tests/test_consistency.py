"""Consistency between the spec, the rule model and the run evidence (issue #76).

What each check means is in ``explorer.consistency``'s docstring, along with the checks
that already live in other test files and aren't repeated here (fixtures, matrix rows,
smoke runs, ConfigSpace agreement).
"""

import json

import pytest

from explorer import consistency as C
from explorer import model_json
from explorer.adapter import ADAPTER_TEST
from explorer.rules import load_rules

# --- the committed files -------------------------------------------------------------------


def test_no_evidence_run_breaks_a_rule_unless_labeled_negative():
    assert C.evidence_violations() == [], (
        "a passing evidence run breaks today's rules: label it a negative experiment "
        "(runs/experiments/) or revisit the rule")


def test_cited_runs_pass_every_rule():
    # Smoke runs, anchor runs and contrast sides: no exemption, not even by design.
    assert C.cited_violations() == []


def test_labeled_negatives_stay_out_of_the_evidence_folders():
    assert C.misplaced_negatives() == []


def test_negative_by_design_is_still_needed():
    # Each exemption is used by a committed evidence run, and only for hostap's own tests.
    used = {rule_id for check in C.check_runs(C.EVIDENCE_DIRS) if check.labeled_negative
            and check.test != ADAPTER_TEST for rule_id in check.rule_ids}
    assert used == set(C.NEGATIVE_BY_DESIGN)
    assert set(C.NEGATIVE_BY_DESIGN) <= {r.id for r in load_rules().rules}


def test_every_offered_dimension_value_has_a_smoke_run():
    # model_json.DIMENSIONS is what the planner can choose from. A label without a smoke
    # run would be dropped from model.json without a word, and a dimension that lost its
    # smoke runs would still be offered. (The other direction, a smoke-tested label with
    # no typed value, is test_model_json.test_every_admitted_row_has_a_mapping.)
    admitted = {row["name"]: set(model_json._smoke_runs(row))
                for row in model_json.admitted_rows()}
    assert set(model_json.DIMENSIONS) == set(admitted)
    for name, (_, values) in model_json.DIMENSIONS.items():
        assert set(values) == admitted[name], name


def test_every_rule_has_fixtures_and_its_matrix_rows():
    for entry in C.rule_validation():
        assert entry.fixtures.get("positive") and entry.fixtures.get("negative"), entry.id
        if entry.cites_standard:
            assert entry.matrix_rows, f"{entry.id} cites a standard but no matrix row names it"


def test_committed_validation_json_is_current():
    assert json.loads(C.VALIDATION_JSON.read_text()) == json.loads(C.render()), (
        "rules/validation.json is out of date: run scripts/check_consistency.py")


def test_validation_report():
    data = json.loads(C.VALIDATION_JSON.read_text())
    entries = {e["id"]: e for e in data["rules"]}
    registry = load_rules()
    assert set(entries) == {e.id for e in [*registry.rules, *registry.undetermined]}
    assert data["unvalidated"] == [i for i, e in entries.items() if e["validation"] == "none"]
    assert sum(data["counts"].values()) == len(entries)
    # The official baseline breaks SEC.EHT_SAE_AKM, and hostapd accepts it.
    baseline = [r for r in entries["SEC.EHT_SAE_AKM"]["broken_in_runs"]
                if r["run"].startswith("runs/baseline/")]
    assert len(baseline) == 3 and {r["result"] for r in baseline} == {"PASS"}
    # #95's labeled experiment is what validates SEC.MLD_SAME_RSNXE.
    assert {"run": "runs/experiments/1794875139", "test": ADAPTER_TEST, "result": "PASS"} \
        in entries["SEC.MLD_SAME_RSNXE"]["broken_in_runs"]


# --- the checks themselves, on made-up runs --------------------------------------------------


def _legal():
    return model_json.base_candidate()


def _no_client_bp():
    candidate = _legal()
    candidate["config"]["sta"]["beacon_protection"] = False
    return candidate


def _write_run(folder, run_id, test, result="PASS", candidate=None, negative=False):
    manifest = {"run_id": run_id, "results": [{"test": test, "result": result}]}
    if candidate is not None:
        manifest["explorer_plan"] = {"explorer": {"candidate": candidate,
                                                  "negative_experiment": negative}}
    (folder / run_id).mkdir(parents=True)
    (folder / run_id / "manifest.json").write_text(json.dumps(manifest))


def test_an_unlabeled_rule_breaking_adapter_run_is_flagged(tmp_path):
    _write_run(tmp_path, "1", ADAPTER_TEST, candidate=_legal())
    _write_run(tmp_path, "2", ADAPTER_TEST, candidate=_no_client_bp())
    _write_run(tmp_path, "3", ADAPTER_TEST, result="FAIL", candidate=_no_client_bp())
    flagged = C.evidence_violations([tmp_path])
    assert [(c.run_id, c.rule_ids) for c in flagged] == [("2", ["SEC.EHT_BEACON_PROT"])]


def test_a_labeled_negative_adapter_run_isnt_a_violation_but_is_misplaced(tmp_path):
    _write_run(tmp_path, "1", ADAPTER_TEST, candidate=_no_client_bp(), negative=True)
    assert C.evidence_violations([tmp_path]) == []
    assert [c.run_id for c in C.misplaced_negatives([tmp_path])] == ["1"]


def test_hostap_originals_are_negative_by_design_but_wrappers_are_not(tmp_path):
    _write_run(tmp_path, "1", "eht_mld_sae_ext_two_links")
    _write_run(tmp_path, "2", "eht_mld_sae_ext_two_links_client_bp")
    checks = {c.run_id: c for c in C.check_runs([tmp_path])}
    assert checks["1"].rule_ids == ["SEC.EHT_BEACON_PROT"] and checks["1"].labeled_negative
    assert checks["2"].rule_ids == [] and not checks["2"].labeled_negative
    assert C.evidence_violations([tmp_path]) == []


def test_an_exemption_covers_only_its_own_rules(tmp_path, monkeypatch):
    _write_run(tmp_path, "1", "eht_mld_sae_ext_two_links")
    monkeypatch.setattr(C, "NEGATIVE_BY_DESIGN", {"SEC.EHT_SAE_AKM": "baseline"})
    assert [c.run_id for c in C.evidence_violations([tmp_path])] == ["1"]


def test_a_candidate_that_no_longer_parses_is_a_violation(tmp_path):
    candidate = _legal()
    candidate["config"]["ap"]["no_such_setting"] = 1
    _write_run(tmp_path, "1", ADAPTER_TEST, candidate=candidate)
    assert [c.rule_ids for c in C.evidence_violations([tmp_path])] == [["P0"]]


def test_hostap_tests_without_a_scenario_are_skipped(tmp_path):
    _write_run(tmp_path, "1", "eht_some_unmodeled_test")
    assert C.check_runs([tmp_path]) == []


@pytest.mark.parametrize("cited, expected", [
    ({"1793897820": ["anchor F02"]}, []),
    ({"999": ["made up"]}, [(None, ["made up"])]),
])
def test_cited_runs_must_exist_and_pass(monkeypatch, cited, expected):
    monkeypatch.setattr(C, "cited_runs", lambda: cited)
    assert C.cited_violations() == expected


def test_citing_a_negative_by_design_run_as_evidence_is_flagged(monkeypatch):
    # The baseline is exempt as an evidence-folder run, but never as cited evidence.
    monkeypatch.setattr(C, "cited_runs", lambda: {"1793298094": ["smoke SAE"]})
    [(check, where)] = C.cited_violations()
    assert check.rule_ids == ["SEC.EHT_SAE_AKM"] and check.labeled_negative
    assert where == ["smoke SAE"]
