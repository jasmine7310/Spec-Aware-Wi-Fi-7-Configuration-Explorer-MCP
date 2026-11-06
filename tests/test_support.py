import json

import pytest

from explorer.model import Candidate
from explorer.scenarios import TEST_CANDIDATES, TEST_CONFIGS
from explorer.support import (EVIDENCE_DIRS, action_key, check_support, passing_runs,
                              setting_values, smoke_evidence)

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
    result = check_support(_candidate("eht_mld_owe_two_links_client_bp", [
        ASSOC, {"action": "sta_disconnect_reconnect", "command": "DISCONNECT"},
        {"action": "sta_disconnect_reconnect", "command": "RECONNECT"}]))
    evidence = {(v.candidate, v.value): v.run_ids for v in result.values}
    assert evidence[("sta_disconnect_reconnect", "DISCONNECT")]   # the OWE tests do it
    assert evidence[("sta_disconnect_reconnect", "RECONNECT")] == []
    assert "sta_disconnect_reconnect=RECONNECT" in result.note


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
