import pytest

from explorer.model import Config
from explorer.rules import load_rules
from explorer.scenarios import TEST_CONFIGS
from explorer.validate import (CONFIG_QUESTIONS, P1_CHECKS, Finding, check_eht_sae_akm,
                               check_mld_client_common_akm, check_mld_common_suites,
                               find_undetermined, p1_status, run_p1_checks)


def _config(link0, link1, sta_akms, **ap):
    return Config.model_validate({
        "ap": {"links": [{"link_id": 0, "channel": 1, **link0},
                         {"link_id": 1, "channel": 6, **link1}], **ap},
        "sta": {"akms": sta_akms},
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

def test_runnable_tests_other_than_plain_sae_pass_modeled_rules():
    failing = {name for name, config in TEST_CONFIGS.items() if run_p1_checks(config)}
    assert failing == {"eht_mld_sae_two_links"}


def test_every_check_has_a_rule_in_the_registry():
    registry = load_rules()
    for rule_id in P1_CHECKS:
        assert registry.get(rule_id).kind in {"normative", "dependency"}, rule_id
    for question_id in CONFIG_QUESTIONS:
        assert question_id in {q.id for q in registry.undetermined}


# --- SPEC_UNDETERMINED (configuration questions) ---

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
