import copy

from explorer.scenarios import TEST_CONFIGS
from explorer.validate import validate_candidate

ASSOC = {"action": "associate"}
REKEY = {"action": "rekey_gtk_now"}


def _config(name):
    return TEST_CONFIGS[name].model_dump()


def _ids(result):
    return [f.rule_id for f in result.findings]


# --- The Checkpoint 1 cases ---------------------------------------------------

def test_malformed_candidate_stops_at_p0():
    config = _config("eht_mld_sae_ext_two_links")
    config["ap"]["links"][0]["link_id"] = "0"
    result = validate_candidate({"config": config, "actions": [ASSOC]})

    assert (result.status, result.stage_reached) == ("MALFORMED", "P0")
    assert [f"{f.rule_id}: {f.reason}" for f in result.findings] == [
        "P0.TYPE_ERROR: config.ap.links[0].link_id must be an integer"]
    assert result.findings[0].kind == "format"


def test_link_akm_intersection_is_rejected_with_its_source():
    # hostap's test_eht_mld_no_common_key_mgmt: link 0 SAE, link 1 SAE-EXT-KEY.
    config = _config("eht_mld_sae_ext_two_links")
    config["ap"]["links"][0]["akms"] = ["SAE"]
    config["sta"]["akms"] = ["SAE", "SAE-EXT-KEY"]
    result = validate_candidate({"config": config, "actions": [ASSOC]})

    assert (result.status, result.stage_reached) == ("SPEC_RULE_VIOLATION", "P1")
    finding = next(f for f in result.findings if f.rule_id == "SEC.MLD_COMMON_SUITES")
    assert finding.kind == "normative"
    assert "no common AKM" in finding.reason
    assert any(s.startswith("IEEE-802.11be-2024 §12.6.2") and s.endswith("(shall)")
               for s in finding.sources)


def test_action_order_is_rejected():
    result = validate_candidate({"config": _config("eht_mld_sae_ext_two_links"),
                                 "actions": [REKEY, ASSOC]})
    assert result.status == "SPEC_RULE_VIOLATION"
    assert _ids(result) == ["AO.ASSOC_REQUIRED"]
    assert result.findings[0].kind == "harness"
    assert "not that it breaks the Wi-Fi specification" in result.note


def test_undetermined_candidate():
    config = _config("eht_mld_sae_ext_two_links")
    for link in config["ap"]["links"]:
        link["akms"] = ["SAE-EXT-KEY", "WPA-PSK"]
    config["sta"]["akms"] = ["WPA-PSK", "SAE-EXT-KEY"]
    result = validate_candidate({"config": config, "actions": [ASSOC]})

    assert result.status == "SPEC_UNDETERMINED"
    assert _ids(result) == ["UND.AKM_PREFERENCE"]
    assert result.findings[0].kind == "open_question"
    assert result.findings[0].sources[0].startswith("WFA-WPA3 Table 3")


def test_legal_candidate_passes_modeled_rules_only():
    result = validate_candidate({"config": _config("eht_mld_sae_ext_two_links"),
                                 "actions": [ASSOC, REKEY]})
    assert (result.status, result.findings) == ("PASSES_MODELED_RULES", [])
    assert "not full 802.11be compliance" in result.note
    assert result.p2 == "NOT_CHECKED"


def test_plain_sae_baseline_is_a_violation():
    result = validate_candidate({"config": _config("eht_mld_sae_two_links"), "actions": [ASSOC]})
    assert _ids(result) == ["SEC.EHT_SAE_AKM"]
    assert any("§12.12.9" in s for s in result.findings[0].sources)


# --- Combining findings ---------------------------------------------------------

def test_all_p1_findings_are_reported_together():
    config = _config("eht_mld_sae_ext_two_links")
    config["ap"]["beacon_protection"] = False
    result = validate_candidate({"config": config, "actions": [REKEY]})
    assert _ids(result) == ["SEC.EHT_BEACON_PROT", "AO.ASSOC_REQUIRED"]


def test_violation_outweighs_an_open_question():
    config = _config("eht_mld_sae_ext_two_links")
    for link in config["ap"]["links"]:
        link["akms"] = ["SAE-EXT-KEY", "WPA-PSK"]
    config["sta"]["akms"] = ["WPA-PSK", "SAE-EXT-KEY"]
    config["ap"]["beacon_protection"] = False
    result = validate_candidate({"config": config})
    assert result.status == "SPEC_RULE_VIOLATION"
    assert _ids(result) == ["SEC.EHT_BEACON_PROT", "UND.AKM_PREFERENCE"]


def test_every_runnable_hostap_config_gets_the_status_run_hwsim_test_reports():
    for name, config in TEST_CONFIGS.items():
        result = validate_candidate({"config": config.model_dump()})
        expected = "SPEC_RULE_VIOLATION" if name == "eht_mld_sae_two_links" else "PASSES_MODELED_RULES"
        assert result.status == expected, name


def test_input_is_not_modified():
    data = {"config": _config("eht_mld_sae_ext_two_links"), "actions": [ASSOC]}
    before = copy.deepcopy(data)
    validate_candidate(data)
    assert data == before
