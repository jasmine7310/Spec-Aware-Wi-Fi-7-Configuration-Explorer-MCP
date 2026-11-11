import json

import pytest

from explorer.model import Candidate
from explorer.scenarios import TEST_CANDIDATES, TEST_CONFIGS
from explorer.support import (EVIDENCE_DIRS, action_key, adapter_runs, check_support,
                              passing_runs, rule_passing_tests, setting_values,
                              smoke_evidence)

ASSOC = {"action": "associate"}
CLIENT_BP_TESTS = sorted(name for name in TEST_CANDIDATES if name.endswith("_client_bp"))


def _candidate(test, actions):
    return Candidate.model_validate({"config": TEST_CONFIGS[test], "actions": actions})


# --- SUPPORTED: a tested scenario executes the candidate exactly ---

@pytest.mark.parametrize("test", CLIENT_BP_TESTS)
def test_every_client_bp_scenario_is_supported(test):
    result = check_support(TEST_CANDIDATES[test])
    assert (result.status, result.test) == ("SUPPORTED", test)
    assert len(result.run_ids) >= 1
    assert result.values == [] and result.closest_tests == []


def test_supported_run_ids_are_passing_committed_runs_of_that_test():
    result = check_support(TEST_CANDIDATES["eht_mld_link_removal_client_bp"])
    for run_id in result.run_ids:
        folder = next(d / run_id for d in EVIDENCE_DIRS if (d / run_id).is_dir())
        results = json.loads((folder / "manifest.json").read_text())["results"]
        assert any(r["test"] == "eht_mld_link_removal_client_bp" and r["result"] == "PASS"
                   for r in results), run_id


def test_a_test_without_committed_runs_is_unresolved():
    # The BSS TM test has a known scenario but no committed run.
    result = check_support(TEST_CANDIDATES["eht_mld_bss_trans_mgmt_link_removal_imminent"])
    assert result.status == "UNRESOLVED"


# --- UNRESOLVED: anything else, with the evidence behind each value ---

def test_recombined_values_are_unresolved_with_their_evidence():
    # SAE-EXT-KEY and link removal each have smoke runs, but no test combines them.
    result = check_support(_candidate("eht_mld_sae_ext_two_links_client_bp", [
        ASSOC, {"action": "link_remove", "link_id": 1, "count": 4}]))
    assert result.status == "UNRESOLVED"
    evidence = {(v.candidate, v.value): v.run_ids for v in result.values}
    assert evidence[("ap_akm", "SAE-EXT-KEY")]
    assert evidence[("link_remove", "present")]
    assert all(evidence.values())
    assert "not in this combination" in result.note
    assert result.closest_tests == ["eht_mld_sae_ext_two_links_client_bp"]


def test_value_without_a_smoke_run_is_named():
    config = TEST_CONFIGS["eht_mld_owe_two_links_client_bp"].model_copy(update={
        "ap": TEST_CONFIGS["eht_mld_owe_two_links_client_bp"].ap.model_copy(
            update={"ptk_rekey_interval_s": 60})})
    result = check_support(Candidate.model_validate({"config": config, "actions": [ASSOC]}))
    assert result.status == "UNRESOLVED"
    assert "ap_ptk_rekey_interval=60" in result.note
    assert result.closest_tests == []


def test_action_never_run_has_no_evidence():
    # No legal committed run sends DISASSOCIATE (hostap's eht_mld_disassociate isn't a
    # runnable scenario, and no adapter run has it).
    result = check_support(_candidate("eht_mld_owe_two_links_client_bp", [
        ASSOC, {"action": "sta_disconnect_reconnect", "command": "DISCONNECT"},
        {"action": "ap_disassociate"}]))
    evidence = {(v.candidate, v.value): v.run_ids for v in result.values}
    assert evidence[("sta_disconnect_reconnect", "DISCONNECT")]   # the OWE tests do it
    assert evidence[("ap_disassociate", "present")] == []
    assert "ap_disassociate=present" in result.note


def test_only_the_client_bp_tests_pass_the_modeled_rules():
    # hostap's originals leave the client's beacon protection off (SEC.EHT_BEACON_PROT)
    # and the baseline uses plain SAE (SEC.EHT_SAE_AKM).
    assert sorted(rule_passing_tests()) == CLIENT_BP_TESTS


def test_rule_breaking_runs_never_count_as_action_evidence():
    runs = passing_runs()
    legal_runs = {run for test in rule_passing_tests() for run in runs.get(test, [])}
    legal_runs |= set(adapter_runs())   # recorded as passing the modeled rules
    result = check_support(_candidate("eht_mld_sae_ext_two_links_client_bp", [
        ASSOC, {"action": "sta_disconnect_reconnect", "command": "DISCONNECT"},
        {"action": "rekey_gtk_now"}, {"action": "bss_tm_link_removal_imminent"}]))
    evidence = {(v.candidate, v.value): v.run_ids for v in result.values}
    for key in [("associate", "present"), ("sta_disconnect_reconnect", "DISCONNECT"),
                ("rekey_gtk_now", "present")]:
        assert evidence[key] and set(evidence[key]) <= legal_runs, (key, evidence[key])
    # The baseline (plain SAE) and the original link-removal test performed these, but
    # they're negative experiments.
    assert not set(runs["eht_mld_sae_two_links"]) & {r for ids in evidence.values() for r in ids}
    # Only hostap's original BSS TM test sends this request, and it breaks a rule.
    assert evidence[("bss_tm_link_removal_imminent", "present")] == []
    assert "bss_tm_link_removal_imminent=present" in result.note


def test_owe_association_alone_points_at_the_closest_tests():
    # The OWE tests end with DISCONNECT, so [associate] alone isn't an exact match.
    result = check_support(_candidate("eht_mld_owe_two_links_client_bp", [ASSOC]))
    assert result.status == "UNRESOLVED"
    assert "eht_mld_owe_two_links_client_bp" in result.closest_tests


def test_never_unsupported_without_recorded_evidence():
    statuses = {check_support(c).status for c in TEST_CANDIDATES.values()}
    assert "UNSUPPORTED_IMPLEMENTATION" not in statuses


# --- Building blocks ---

def test_setting_values_use_the_csv_labels():
    values = setting_values(TEST_CANDIDATES["eht_mld_ptk_rekey_client_bp"])
    assert ("ap_ptk_rekey_interval", "5") in values
    assert ("ap_gtk_rekey_interval", "unset") in values
    assert ("link_remove", "absent") in values
    for name, label in values:
        if name in smoke_evidence():
            assert label in smoke_evidence()[name] or name in ("ap_akm", "sta_akm"), (name, label)


def test_action_keys_include_the_command():
    candidate = TEST_CANDIDATES["eht_mld_owe_two_links_client_bp"]
    assert [action_key(s) for s in candidate.actions] == [
        ("associate", "present"), ("sta_disconnect_reconnect", "DISCONNECT")]


def test_trial_runs_never_count(tmp_path):
    trial = tmp_path / "hwsim-logs" / "1"
    trial.mkdir(parents=True)
    (trial / "manifest.json").write_text(json.dumps(
        {"run_id": "1", "results": [{"test": "eht_mld_sae_ext_two_links_client_bp", "result": "PASS"}]}))
    assert "1" not in passing_runs().get("eht_mld_sae_ext_two_links_client_bp", [])
    assert passing_runs([tmp_path / "hwsim-logs"]) == {"eht_mld_sae_ext_two_links_client_bp": ["1"]}


# --- The dimensions admitted in #61 and adapter runs as evidence (#90) ------

F02 = "eht_mld_sae_ext_two_links_client_bp"
REJECTED_RUN = "1794384673"   # ap_sae_pwe=1, runs/rejected/
DISABLE_ENABLE = [ASSOC,
                  {"action": "disable_enable_mld", "command": "DISABLE_MLD"},
                  {"action": "sta_disconnect_reconnect", "command": "DISCONNECT"},
                  {"action": "disable_enable_mld", "command": "ENABLE_MLD"},
                  {"action": "sta_disconnect_reconnect", "command": "RECONNECT"}]


def _f02(actions=(ASSOC,), cipher="CCMP", **ap):
    config = TEST_CONFIGS[F02].model_dump()
    config["ap"].update(ap)
    for link in config["ap"]["links"]:
        link["pairwise_cipher"] = cipher
    return Candidate.model_validate({"config": config, "actions": list(actions)})


def _evidence(candidate):
    return {(v.candidate, v.value): v.run_ids for v in check_support(candidate).values}


def test_gcmp_256_cites_its_smoke_run():
    evidence = _evidence(_f02(cipher="GCMP-256"))
    assert evidence[("ap_pairwise_cipher", "GCMP-256")] == ["1794384688"]


def test_sae_pwe_values_use_the_csv_labels():
    assert _evidence(_f02(sae_pwe="both"))[("ap_sae_pwe", "2")] == ["1794384680"]
    # (plain F02 is SUPPORTED, with no per-value list, so use a recombined candidate)
    assert _evidence(_f02(cipher="GCMP-256"))[("ap_sae_pwe", "unset")] == ["1794384666"]
    result = check_support(_f02(sae_pwe="hash_to_element"))
    assert {(v.candidate, v.value): v.run_ids for v in result.values}[("ap_sae_pwe", "1")] == []
    assert "ap_sae_pwe=1" in result.note


def test_new_actions_cite_the_adapter_runs():
    assert _evidence(_f02([ASSOC, {"action": "rekey_gtk_now"}]))[
        ("rekey_gtk_now", "present")] == ["1794384695"]
    evidence = _evidence(_f02(DISABLE_ENABLE))
    assert evidence[("disable_enable_mld", "present")] == ["1794384702"]
    assert "1794384702" in evidence[("disable_enable_mld", "DISABLE_MLD")]
    assert "1794384702" in evidence[("disable_enable_mld", "ENABLE_MLD")]
    assert "1794384702" in evidence[("sta_disconnect_reconnect", "RECONNECT")]


def test_presence_actions_are_listed_once():
    keys = [(v.candidate, v.value) for v in check_support(
        _f02([ASSOC, {"action": "rekey_gtk_now"}])).values]
    assert keys.count(("rekey_gtk_now", "present")) == 1
    assert ("disable_enable_mld", "absent") in keys and ("link_remove", "absent") in keys


def test_rejected_and_rule_breaking_runs_are_never_cited():
    runs = passing_runs()
    rule_breaking = {run for test, ids in runs.items()
                     if test in TEST_CANDIDATES and test not in rule_passing_tests()
                     for run in ids}
    for candidate in [_f02(cipher="GCMP-256"), _f02(sae_pwe="hash_to_element"),
                      _f02(DISABLE_ENABLE), _f02([ASSOC, {"action": "rekey_gtk_now"}])]:
        cited = {run for ids in _evidence(candidate).values() for run in ids}
        assert REJECTED_RUN not in cited
        assert not cited & rule_breaking, cited & rule_breaking
    assert REJECTED_RUN not in adapter_runs()


def _adapter_manifest(folder, run_id, result="PASS", status="PASSES_MODELED_RULES",
                      negative=False, test="explorer_candidate"):
    run = folder / run_id
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({
        "run_id": run_id, "results": [{"test": test, "result": result}],
        "explorer_plan": {"explorer": {
            "negative_experiment": negative,
            "validation": {"status": status, "rule_ids": [], "p2": None},
            "candidate": {"actions": [ASSOC, {"action": "rekey_gtk_now"}]}}}}))


def test_adapter_runs_count_only_passing_rule_passing_runs(tmp_path):
    _adapter_manifest(tmp_path, "1", )
    _adapter_manifest(tmp_path, "2", result="FAIL")                         # REJECTED
    _adapter_manifest(tmp_path, "3", status="SPEC_RULE_VIOLATION", negative=True)
    _adapter_manifest(tmp_path, "4", test="eht_mld_sae_ext_two_links_client_bp")
    (tmp_path / "5").mkdir()
    (tmp_path / "5" / "manifest.json").write_text(json.dumps(
        {"run_id": "5", "results": [{"test": "explorer_candidate", "result": "PASS"}]}))
    assert adapter_runs([tmp_path]) == {"1": [ASSOC, {"action": "rekey_gtk_now"}]}
