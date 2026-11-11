import os

import pytest

from explorer import adapter
from explorer.adapter import (UnsupportedCandidate, build_plan, classify,
                              comparable_signature, unsupported)
from explorer.model import Candidate
from explorer.scenarios import TEST_CANDIDATES, TEST_CONFIGS
from explorer.signatures import BehaviorRecord
from explorer.support import rule_passing_tests

ASSOC = {"action": "associate"}


def _candidate(test, actions=None):
    known = TEST_CANDIDATES[test]
    return Candidate.model_validate({
        "config": TEST_CONFIGS[test],
        "actions": known.model_dump()["actions"] if actions is None else actions})


# --- Plan: AP parameters as eht_mld_ap_wpa2_params() builds them -----------

def test_sae_ext_plan_matches_hostaps_test():
    plan = build_plan(_candidate("eht_mld_sae_ext_two_links_client_bp"))
    link0, link1 = plan["ap_links"]
    assert (link0["link_id"], link0["params"]["channel"]) == (0, "1")
    assert (link1["link_id"], link1["params"]["channel"]) == (1, "6")
    params = link0["params"]
    # hostapd.wpa2_params() + eht_mld_ap_wpa2_params() (test_eht.py:320-338)
    assert params["wpa"] == "2" and params["rsn_pairwise"] == "CCMP"
    assert params["wpa_key_mgmt"] == "SAE-EXT-KEY"
    assert params["wpa_passphrase"] == "qwertyuiop"
    assert params["ieee80211w"] == "2"
    assert params["beacon_prot"] == "1"
    assert params["group_mgmt_cipher"] == "AES-128-CMAC"
    assert "sae_pwe" not in params  # pwe=None in the test
    # wpas.connect(..., key_mgmt="SAE-EXT-KEY", ieee80211w="2") (test_eht.py:826-827),
    # plus beacon_prot as in our _client_bp wrapper
    assert plan["sta"]["connect"] == {"key_mgmt": "SAE-EXT-KEY", "ieee80211w": "2",
                                      "scan_freq": "2412 2437",
                                      "sae_password": "qwertyuiop", "beacon_prot": "1"}
    assert plan["needs_sae"] and not plan["needs_owe"]


def test_owe_has_no_passphrase():
    plan = build_plan(_candidate("eht_mld_owe_two_links_client_bp"))
    assert all("wpa_passphrase" not in link["params"] for link in plan["ap_links"])
    assert plan["sta"]["connect"]["key_mgmt"] == "OWE"
    assert "sae_password" not in plan["sta"]["connect"]
    assert plan["needs_owe"]


def test_link_indicated_disabled():
    plan = build_plan(_candidate("eht_mld_owe_two_links_one_disabled_client_bp"))
    assert "mld_indicate_disabled" not in plan["ap_links"][0]["params"]
    assert plan["ap_links"][1]["params"]["mld_indicate_disabled"] == "1"


def test_rekey_intervals_and_shared_settings():
    plan = build_plan(_candidate("eht_mld_ptk_rekey_client_bp"))
    assert plan["ap_shared"]["wpa_ptk_rekey"] == "5"
    assert plan["ap_links"][0]["params"]["ieee80211w"] == "1"   # mfp="1" in the test
    plan = build_plan(_candidate("eht_mld_gtk_rekey_client_bp"))
    assert plan["ap_shared"]["wpa_group_rekey"] == "5"


def test_actions_pass_through_in_order():
    plan = build_plan(_candidate("eht_mld_link_removal_client_bp"))
    assert [step["action"] for step in plan["actions"]] == [
        "associate", "link_remove", "rekey_gtk_now", "link_remove"]
    assert plan["actions"][1] == {"action": "link_remove", "link_id": 1, "count": 4}


def test_client_off_and_psk_options():
    candidate = Candidate.model_validate({
        "config": {"ap": {"links": [{"link_id": 0, "channel": 6, "akms": ["WPA-PSK"]}],
                          "beacon_protection": False, "sae_pwe": "both",
                          "bss_transition": True},
                   "sta": {"akms": ["WPA-PSK"], "beacon_protection": False,
                           "sae_groups": [19, 20]}},
        "actions": [ASSOC]})
    plan = build_plan(candidate)
    params = plan["ap_links"][0]["params"]
    assert params["beacon_prot"] == "0" and params["sae_pwe"] == "2"
    assert params["bss_transition"] == "1"
    assert plan["sta"]["connect"] == {"key_mgmt": "WPA-PSK", "ieee80211w": "2",
                                      "scan_freq": "2437", "psk": "qwertyuiop"}
    assert plan["sta"]["sae_groups"] == "19 20"


# --- Unsupported candidates are refused before a guest boots ---------------

def test_every_rule_passing_scenario_is_supported():
    for test in rule_passing_tests():
        assert unsupported(TEST_CANDIDATES[test]) == [], test


def test_gcmp_and_unsupported_actions_are_refused():
    base = TEST_CONFIGS["eht_mld_sae_ext_two_links_client_bp"].model_dump()
    for link in base["ap"]["links"]:
        link["pairwise_cipher"] = "GCMP-256"
    candidate = Candidate.model_validate({
        "config": base, "actions": [ASSOC, {"action": "ml_probe_req"}]})
    reasons = unsupported(candidate)
    assert any("GCMP-256" in r for r in reasons)
    assert any("actions[1] (ml_probe_req)" in r for r in reasons)
    with pytest.raises(UnsupportedCandidate):
        build_plan(candidate)


# --- P3 status from the run and the adapter's log markers ------------------

def _record(result):
    return BehaviorRecord.model_construct(test_result=result)


def test_classify():
    assert classify("TIMEOUT", None, "") == ("TIMEOUT", None)
    assert classify("SETUP_FAIL", None, "")[0] == "SETUP_FAIL"
    assert classify("COMPLETED", _record("PASS"), "x\nEXPLORER-DONE\n") == ("ACCEPTED", None)
    assert classify("COMPLETED", _record("FAIL"),
                    "EXPLORER-REJECTED actions[0] associate: Connection timed out\n") == (
        "REJECTED", "actions[0] associate: Connection timed out")
    assert classify("COMPLETED", _record("SKIP"), "")[0] == "SETUP_FAIL"
    status, reason = classify("COMPLETED", _record("FAIL"), "Traceback ...")
    assert status == "SETUP_FAIL" and "didn't finish" in reason
    # PASS without the done marker means the adapter didn't run to the end
    assert classify("COMPLETED", _record("PASS"), "")[0] == "SETUP_FAIL"


def test_comparable_signature_drops_the_test_name(tmp_path):
    from pathlib import Path
    from explorer.signatures import extract_record
    run = Path(__file__).resolve().parent.parent / "runs" / "anchors" / "1793897968"
    signature = comparable_signature(extract_record(run))
    assert "test" not in signature and signature["valid_links"] == "0x3"


# --- Real run (opt-in) -----------------------------------------------------

@pytest.mark.skipif(os.environ.get("WIFI7_DOCKER_TESTS") != "1",
                    reason="set WIFI7_DOCKER_TESTS=1 to run against the real simulation image")
def test_real_candidate_run(tmp_path):
    run = adapter.run_candidate(_candidate("eht_mld_sae_ext_two_links_client_bp"),
                                log_dir=tmp_path)
    assert run.status == "ACCEPTED", (run.reason, run.run_dir)
    signature = comparable_signature(run.record)
    assert signature["station_status"]["key_mgmt"] == "SAE-EXT-KEY"
    assert signature["valid_links"] == signature["active_links"] == "0x3"
    assert signature["data_test_rx_ap_links"] == (0, 1)
    assert (run.run_dir / "explorer_plan.json").exists()
