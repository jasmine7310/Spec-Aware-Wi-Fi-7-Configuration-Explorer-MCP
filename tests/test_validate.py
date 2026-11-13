import pytest

from explorer.model import Config
from explorer.rules import load_rules
from explorer.scenarios import CLIENT_BP_SUFFIX, TEST_CONFIGS
from explorer.validate import (CONFIG_QUESTIONS, P1_CHECKS, Finding, check_eht_beacon_prot,
                               check_eht_sae_akm, check_eht_sae_h2e, check_mld_client_common_akm,
                               check_mld_common_suites, check_sae_h2e_only_needs_sta_h2e,
                               check_sae_pwe_needs_sae, find_undetermined, p1_status,
                               run_p1_checks, validate_candidate)


def _config(link0, link1, sta_akms, sta=None, **ap):
    return Config.model_validate({
        "ap": {"links": [{"link_id": 0, "channel": 1, **link0},
                         {"link_id": 1, "channel": 6, **link1}], **ap},
        "sta": {"akms": sta_akms, **(sta or {})},
    })


# --- SEC.MLD_COMMON_SUITES (802.11be §12.6.2, the AP MLD's own configuration) ---

AP_PASSES = {
    "eht_mld_owe_two_links": TEST_CONFIGS["eht_mld_owe_two_links"],
    "eht_mld_ptk_rekey": TEST_CONFIGS["eht_mld_ptk_rekey"],
    # The roadmap's exception: the AKM lists differ but share an AKM.
    # link_0_akms == link_1_akms would wrongly prune this.
    "different_lists_shared_akm": _config(
        {"akms": ["SAE-EXT-KEY", "SAE"]}, {"akms": ["SAE-EXT-KEY"]}, ["SAE-EXT-KEY"]),
}

# hostap's deliberate failure tests (test_eht.py at the pinned commit); each breaks
# §12.6.2 on the AP side. The client in _test_eht_mld_invalid_link allows
# "WPA-PSK SAE SAE-EXT-KEY".
AP_REJECTED = {
    # test_eht_mld_invalid_link: link 0 WPA-PSK, link 1 SAE
    "eht_mld_invalid_link": (
        _config({"akms": ["WPA-PSK"]}, {"akms": ["SAE"]}, ["WPA-PSK", "SAE", "SAE-EXT-KEY"]),
        "no common AKM"),
    # test_eht_mld_invalid_link_akm: link 0 SAE-EXT-KEY, link 1 SAE
    "eht_mld_invalid_link_akm": (
        _config({"akms": ["SAE-EXT-KEY"]}, {"akms": ["SAE"]}, ["WPA-PSK", "SAE", "SAE-EXT-KEY"]),
        "no common AKM"),
    # test_eht_mld_invalid_link_pairwise: GCMP-256 on link 0 only
    "eht_mld_invalid_link_pairwise": (
        _config({"akms": ["SAE"], "pairwise_cipher": "GCMP-256"}, {"akms": ["SAE"]},
                ["WPA-PSK", "SAE", "SAE-EXT-KEY"]),
        "different pairwise ciphers"),
    # test_eht_mld_no_common_key_mgmt: link 0 SAE, link 1 SAE-EXT-KEY
    "eht_mld_no_common_key_mgmt": (
        _config({"akms": ["SAE"]}, {"akms": ["SAE-EXT-KEY"]}, ["SAE", "SAE-EXT-KEY"]),
        "no common AKM"),
}


@pytest.mark.parametrize("name", AP_PASSES)
def test_mld_common_suites_passes(name):
    assert check_mld_common_suites(AP_PASSES[name]) == []


@pytest.mark.parametrize("name", AP_REJECTED)
def test_mld_common_suites_rejects(name):
    config, expected = AP_REJECTED[name]
    violations = check_mld_common_suites(config)
    assert [v.rule_id for v in violations] == ["SEC.MLD_COMMON_SUITES"]
    assert violations[0].stage == "P1"
    assert expected in violations[0].reason


def test_mld_common_suites_ignores_the_client():
    # §12.6.2 constrains what the AP MLD advertises, not which AKMs the client allows.
    config = _config({"akms": ["SAE-EXT-KEY"]}, {"akms": ["SAE-EXT-KEY"]}, ["SAE"])
    assert check_mld_common_suites(config) == []


def test_reports_cipher_and_akm_problems_together():
    config = _config({"akms": ["SAE"], "pairwise_cipher": "GCMP-256"},
                     {"akms": ["SAE-EXT-KEY"]}, ["SAE"])
    reasons = [v.reason for v in check_mld_common_suites(config)]
    assert len(reasons) == 2
    assert "link 0 GCMP-256, link 1 CCMP" in reasons[0]
    assert "link 0 ['SAE'], link 1 ['SAE-EXT-KEY']" in reasons[1]


def test_single_link_ap_passes():
    config = Config.model_validate({
        "ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["OWE"]}]},
        "sta": {"akms": ["OWE"]}})
    assert run_p1_checks(config) == []


# --- SEC.MLD_CLIENT_COMMON_AKM (802.11be §12.6.3.1, the client's selection) ---

def test_client_allowing_a_common_akm_passes():
    config = _config({"akms": ["SAE"]}, {"akms": ["SAE", "SAE-EXT-KEY"]}, ["SAE-EXT-KEY", "SAE"])
    assert check_mld_client_common_akm(config) == []


def test_client_without_a_common_akm_declines():
    config = _config({"akms": ["SAE", "SAE-EXT-KEY"]}, {"akms": ["SAE-EXT-KEY"]}, ["SAE"])
    violations = check_mld_client_common_akm(config)
    assert [v.rule_id for v in violations] == ["SEC.MLD_CLIENT_COMMON_AKM"]
    assert "declines the ML association" in violations[0].reason
    # Not reported as an AP-side fault.
    assert check_mld_common_suites(config) == []


def test_client_check_leaves_no_common_akm_to_the_ap_rule():
    config, _ = AP_REJECTED["eht_mld_no_common_key_mgmt"]
    assert check_mld_client_common_akm(config) == []


# --- SEC.EHT_SAE_AKM (802.11be §12.12.9) ---

def test_plain_sae_between_eht_devices_is_rejected():
    violations = check_eht_sae_akm(TEST_CONFIGS["eht_mld_sae_two_links"])
    assert [v.rule_id for v in violations] == ["SEC.EHT_SAE_AKM"]
    assert "AKM 8" in violations[0].reason


@pytest.mark.parametrize("name", ["eht_mld_sae_ext_two_links", "eht_mld_ptk_rekey",
                                  "eht_mld_owe_two_links"])
def test_sae_ext_key_or_no_sae_passes(name):
    assert check_eht_sae_akm(TEST_CONFIGS[name]) == []


def test_client_offering_both_sae_akms_passes():
    # A conforming client picks AKM 24 when both are available.
    config = _config({"akms": ["SAE-EXT-KEY", "SAE"]}, {"akms": ["SAE-EXT-KEY", "SAE"]},
                     ["SAE", "SAE-EXT-KEY"])
    assert check_eht_sae_akm(config) == []


def test_ap_offering_sae_ext_key_doesnt_help_a_plain_sae_client():
    config = _config({"akms": ["SAE-EXT-KEY", "SAE"]}, {"akms": ["SAE-EXT-KEY", "SAE"]},
                     ["SAE"])
    assert [v.rule_id for v in check_eht_sae_akm(config)] == ["SEC.EHT_SAE_AKM"]


# --- All checks ---

def test_only_the_client_beacon_protection_wrappers_pass_modeled_rules():
    passing = {name for name, config in TEST_CONFIGS.items() if not run_p1_checks(config)}
    assert passing == {name for name in TEST_CONFIGS if name.endswith(CLIENT_BP_SUFFIX)}


def test_every_check_has_a_rule_in_the_registry():
    registry = load_rules()
    for rule_id in P1_CHECKS:
        assert registry.get(rule_id).kind in {"normative", "dependency"}, rule_id
    for question_id in CONFIG_QUESTIONS:
        assert question_id in {q.id for q in registry.undetermined}


# --- SEC.EHT_BEACON_PROT (802.11be §12.12.9) ---

def test_beacon_protection_on_passes():
    assert check_eht_beacon_prot(TEST_CONFIGS["eht_mld_sae_ext_two_links_client_bp"]) == []


def test_client_beacon_protection_off_is_rejected():
    # test_eht_mld_sae_ext_two_links leaves the client's beacon_prot unset (test_eht.py:826-827).
    findings = check_eht_beacon_prot(TEST_CONFIGS["eht_mld_sae_ext_two_links"])
    assert [f.rule_id for f in findings] == ["SEC.EHT_BEACON_PROT"]
    assert "client" in findings[0].reason


def test_beacon_protection_off_is_rejected():
    # test_eht_mld_sae_two_links_no_beacon_prot: beacon_prot=0 (test_eht.py:767-773)
    config = _config({"akms": ["SAE"]}, {"akms": ["SAE"]}, ["SAE"],
                     sae_pwe="hash_to_element", beacon_protection=False)
    assert [f.rule_id for f in check_eht_beacon_prot(config)] == ["SEC.EHT_BEACON_PROT"]


# --- SEC.EHT_SAE_H2E (802.11be §12.12.9) ---

@pytest.mark.parametrize("name", ["eht_mld_sae_two_links",     # SAE with sae_pwe=1
                                  "eht_mld_sae_ext_two_links",  # SAE-EXT-KEY, sae_pwe unset
                                  "eht_mld_owe_two_links"])     # no SAE at all
def test_h2e_in_effect_passes(name):
    assert check_eht_sae_h2e(TEST_CONFIGS[name]) == []


def test_plain_sae_with_unset_pwe_is_rejected():
    # Neither side sets sae_pwe: both would use hunting-and-pecking.
    config = _config({"akms": ["SAE"]}, {"akms": ["SAE"]}, ["SAE"])
    findings = check_eht_sae_h2e(config)
    assert [f.rule_id for f in findings] == ["SEC.EHT_SAE_H2E"] * 2
    assert "AP's sae_pwe" in findings[0].reason and "client's sae_pwe" in findings[1].reason
    assert "hunting-and-pecking" in findings[0].reason


def test_plain_sae_client_with_unset_pwe_is_rejected():
    # The AP enables H2E, but a client with sae_pwe unset uses hunting-and-pecking with
    # plain SAE (wpa_supplicant.conf:501-509), so SAE between them doesn't use H2E.
    config = _config({"akms": ["SAE"]}, {"akms": ["SAE"]}, ["SAE"], sae_pwe="both")
    findings = check_eht_sae_h2e(config)
    assert [f.rule_id for f in findings] == ["SEC.EHT_SAE_H2E"]
    assert "client's sae_pwe" in findings[0].reason


def test_sae_ext_key_preferred_so_unset_pwe_is_fine():
    config = _config({"akms": ["SAE-EXT-KEY", "SAE"]}, {"akms": ["SAE-EXT-KEY", "SAE"]},
                     ["SAE", "SAE-EXT-KEY"])
    assert check_eht_sae_h2e(config) == []


# --- SEC.SAE_PWE_NEEDS_SAE (setting dependency) ---

def test_sae_pwe_with_sae_passes():
    assert check_sae_pwe_needs_sae(TEST_CONFIGS["eht_mld_sae_two_links"]) == []


def test_sae_pwe_with_owe_is_rejected():
    config = _config({"akms": ["OWE"]}, {"akms": ["OWE"]}, ["OWE"], sae_pwe="hash_to_element")
    findings = check_sae_pwe_needs_sae(config)
    assert [f.rule_id for f in findings] == ["SEC.SAE_PWE_NEEDS_SAE"]
    assert "no effect" in findings[0].reason


def test_client_sae_pwe_without_an_sae_akm_is_rejected():
    config = _config({"akms": ["OWE"]}, {"akms": ["OWE"]}, ["OWE"],
                     sta={"sae_pwe": "both"})
    findings = check_sae_pwe_needs_sae(config)
    assert [f.rule_id for f in findings] == ["SEC.SAE_PWE_NEEDS_SAE"]
    assert "client's sae_pwe" in findings[0].reason


def test_client_sae_pwe_with_sae_ext_key_passes():
    config = _config({"akms": ["SAE-EXT-KEY"]}, {"akms": ["SAE-EXT-KEY"]}, ["SAE-EXT-KEY"],
                     sta={"sae_pwe": "hash_to_element"})
    assert check_sae_pwe_needs_sae(config) == []


# --- SEC.SAE_H2E_ONLY_NEEDS_STA_H2E (setting dependency, issue #88) ---

_SAE_EXT = {"akms": ["SAE-EXT-KEY"]}


def test_h2e_only_ap_with_unset_client_is_rejected():
    # The run that found it: AP sae_pwe=1 on F02, client sae_pwe unset (REJECTED).
    config = _config(_SAE_EXT, _SAE_EXT, ["SAE-EXT-KEY"], sae_pwe="hash_to_element")
    findings = check_sae_h2e_only_needs_sta_h2e(config)
    assert [f.rule_id for f in findings] == ["SEC.SAE_H2E_ONLY_NEEDS_STA_H2E"]
    assert "[0, 1]" in findings[0].reason


@pytest.mark.parametrize("sta_pwe", ["hash_to_element", "both"])
def test_h2e_only_ap_with_client_h2e_passes(sta_pwe):
    config = _config(_SAE_EXT, _SAE_EXT, ["SAE-EXT-KEY"], sta={"sae_pwe": sta_pwe},
                     sae_pwe="hash_to_element")
    assert check_sae_h2e_only_needs_sta_h2e(config) == []
    assert run_p1_checks(config) == []


@pytest.mark.parametrize("ap", [{}, {"sae_pwe": "both"}], ids=["ap_unset", "ap_both"])
def test_no_h2e_only_selector_no_requirement(ap):
    # Without sae_pwe=1 the AP doesn't advertise the selector (ieee802_11.c:166-170).
    config = _config(_SAE_EXT, _SAE_EXT, ["SAE-EXT-KEY"], **ap)
    assert check_sae_h2e_only_needs_sta_h2e(config) == []


def test_a_non_sae_akm_on_every_link_means_no_selector():
    # wpa_key_mgmt_only_sae (defs.h:133-140) is false with OWE in the list.
    link = {"akms": ["SAE-EXT-KEY", "OWE"]}
    config = _config(link, link, ["SAE-EXT-KEY"], sae_pwe="hash_to_element")
    assert check_sae_h2e_only_needs_sta_h2e(config) == []


def test_one_sae_only_link_is_enough():
    config = _config(_SAE_EXT, {"akms": ["SAE-EXT-KEY", "OWE"]}, ["SAE-EXT-KEY"],
                     sae_pwe="hash_to_element")
    findings = check_sae_h2e_only_needs_sta_h2e(config)
    assert len(findings) == 1 and "[0]" in findings[0].reason


def test_client_without_an_sae_akm_isnt_checked():
    config = _config(_SAE_EXT, _SAE_EXT, ["OWE"], sae_pwe="hash_to_element")
    assert check_sae_h2e_only_needs_sta_h2e(config) == []


def test_recorded_refusal_is_what_the_rule_predicts():
    # runs/rejected/1794384673 ran this candidate when it still passed the modeled rules;
    # since issue #88 P1 rejects it, for the reason the run showed.
    import json
    from pathlib import Path
    manifest = (Path(__file__).resolve().parents[1] / "runs" / "rejected" / "1794384673"
                / "manifest.json")
    candidate = json.loads(manifest.read_text())["explorer_plan"]["explorer"]["candidate"]
    result = validate_candidate(candidate)
    assert result.status == "SPEC_RULE_VIOLATION"
    assert [f.rule_id for f in result.findings] == ["SEC.SAE_H2E_ONLY_NEEDS_STA_H2E"]


# --- SPEC_UNDETERMINED (configuration questions) ---

@pytest.mark.parametrize("other", ["OWE", "WPA-PSK"])
def test_plain_sae_with_another_family_is_undetermined_not_a_violation(other):
    # The negotiated AKM is unknown, so the SAE rules can't say it breaks them.
    config = _config({"akms": [other, "SAE"]}, {"akms": [other, "SAE"]}, [other, "SAE"])
    assert run_p1_checks(config) == []
    assert [f.rule_id for f in find_undetermined(config)] == ["UND.AKM_PREFERENCE"]


def test_akm_families_mixed_is_undetermined():
    config = _config({"akms": ["SAE-EXT-KEY", "WPA-PSK"]}, {"akms": ["SAE-EXT-KEY", "WPA-PSK"]},
                     ["WPA-PSK", "SAE-EXT-KEY"])
    findings = find_undetermined(config)
    assert [(f.rule_id, f.outcome) for f in findings] == [
        ("UND.AKM_PREFERENCE", "SPEC_UNDETERMINED")]
    assert run_p1_checks(config) == []
    assert p1_status(run_p1_checks(config) + findings) == "SPEC_UNDETERMINED"


@pytest.mark.parametrize("name", sorted(TEST_CONFIGS))
def test_runnable_tests_have_no_open_questions(name):
    # The rekey tests' AP offers PSK too, but their client only allows SAE-EXT-KEY.
    assert find_undetermined(TEST_CONFIGS[name]) == []


def test_two_sae_akms_are_one_family():
    config = _config({"akms": ["SAE-EXT-KEY", "SAE"]}, {"akms": ["SAE-EXT-KEY", "SAE"]},
                     ["SAE", "SAE-EXT-KEY"])
    assert find_undetermined(config) == []


def test_status_precedence():
    violation = Finding(rule_id="SEC.EHT_SAE_AKM", reason="x")
    question = Finding(outcome="SPEC_UNDETERMINED", rule_id="UND.AKM_PREFERENCE", reason="y")
    assert p1_status([]) == "PASSES_MODELED_RULES"
    assert p1_status([question]) == "SPEC_UNDETERMINED"
    assert p1_status([question, violation]) == "SPEC_RULE_VIOLATION"
