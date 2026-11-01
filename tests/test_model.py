import copy
import json

import pytest
from pydantic import ValidationError

from explorer.model import PMF_TO_IEEE80211W, SAE_PWE_TO_HOSTAPD, Config


def _two_links(akms, **ap):
    return {"links": [{"link_id": 0, "channel": 1, "akms": akms},
                      {"link_id": 1, "channel": 6, "akms": akms}], **ap}


# Configurations mirroring real hostap tests at the pinned commit (test_eht.py).
REAL_TEST_CONFIGS = {
    # run_eht_mld_sae_two_links: SAE, mfp=2, pwe=1, beacon_prot=1; STA sae_groups "20 19"
    "eht_mld_sae_two_links": {
        "ap": _two_links(["SAE"], pmf="required", sae_pwe="hash_to_element",
                         beacon_protection=True),
        "sta": {"akms": ["SAE"], "sae_groups": [20, 19]},
    },
    # test_eht_mld_sae_two_links_no_beacon_prot: beacon_prot=0
    "eht_mld_sae_two_links_no_beacon_prot": {
        "ap": _two_links(["SAE"], sae_pwe="hash_to_element", beacon_protection=False),
        "sta": {"akms": ["SAE"], "sae_groups": [20, 19]},
    },
    # _eht_mld_owe_two_links: OWE, mfp=2
    "eht_mld_owe_two_links": {
        "ap": _two_links(["OWE"]),
        "sta": {"akms": ["OWE"]},
    },
    # test_eht_mld_ptk_rekey: mixed AKM list, mfp=1, wpa_ptk_rekey=5; STA SAE-EXT-KEY
    "eht_mld_ptk_rekey": {
        "ap": _two_links(["SAE-EXT-KEY", "SAE", "WPA-PSK", "WPA-PSK-SHA256"],
                         pmf="optional", ptk_rekey_interval_s=5),
        "sta": {"akms": ["SAE-EXT-KEY"]},
    },
    # test_eht_mld_gtk_rekey: same, wpa_group_rekey=5
    "eht_mld_gtk_rekey": {
        "ap": _two_links(["SAE-EXT-KEY", "SAE", "WPA-PSK", "WPA-PSK-SHA256"],
                         pmf="optional", gtk_rekey_interval_s=5),
        "sta": {"akms": ["SAE-EXT-KEY"]},
    },
    # test_eht_mld_owe_two_links_one_disabled: mld_indicate_disabled=1 on link 1
    "eht_mld_owe_two_links_one_disabled": {
        "ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["OWE"]},
                         {"link_id": 1, "channel": 6, "akms": ["OWE"],
                          "indicate_disabled": True}]},
        "sta": {"akms": ["OWE"]},
    },
    # test_eht_mld_bss_trans_mgmt_link_removal_imminent: bss_transition=1
    "eht_mld_bss_trans_mgmt_link_removal_imminent": {
        "ap": _two_links(["OWE"], bss_transition=True),
        "sta": {"akms": ["OWE"]},
    },
    # test_eht_mld_no_common_key_mgmt: link 0 SAE, link 1 SAE-EXT-KEY
    "eht_mld_no_common_key_mgmt": {
        "ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE"]},
                         {"link_id": 1, "channel": 6, "akms": ["SAE-EXT-KEY"]}],
               "sae_pwe": "hash_to_element"},
        "sta": {"akms": ["SAE", "SAE-EXT-KEY"]},
    },
    # test_eht_mld_invalid_link_pairwise: GCMP-256 on link 0 only
    "eht_mld_invalid_link_pairwise": {
        "ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["SAE"],
                          "pairwise_cipher": "GCMP-256"},
                         {"link_id": 1, "channel": 6, "akms": ["SAE"]}],
               "sae_pwe": "hash_to_element"},
        "sta": {"akms": ["SAE"]},
    },
}
BASE = REAL_TEST_CONFIGS["eht_mld_sae_two_links"]


@pytest.mark.parametrize("name", REAL_TEST_CONFIGS)
def test_real_test_configs_are_well_formed(name):
    Config.model_validate(REAL_TEST_CONFIGS[name])


def test_defaults():
    config = Config.model_validate(
        {"ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["OWE"]}]},
         "sta": {"akms": ["OWE"]}})
    assert config.ap.pmf == "required"
    assert config.ap.beacon_protection is True
    assert config.ap.sae_pwe is None
    assert config.ap.ptk_rekey_interval_s is None
    assert config.ap.links[0].pairwise_cipher == "CCMP"
    assert config.ap.links[0].indicate_disabled is False
    assert config.sta.sae_groups is None


def test_accepts_json_input():
    config = Config.model_validate_json(json.dumps(BASE))
    assert config.ap.links[1].channel == 6


def test_hostap_value_maps_match_hostapd_conf():
    # hostapd.conf: ieee80211w 1 = optional, 2 = required; sae_pwe 1 = H2E only, 2 = both.
    assert PMF_TO_IEEE80211W == {"optional": 1, "required": 2}
    assert SAE_PWE_TO_HOSTAPD == {"hash_to_element": 1, "both": 2}


# --- Malformed candidates (P0 rejections) -------------------------------------

def _set(path, value):
    def mutate(d):
        target = d
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


def _delete(path):
    def mutate(d):
        target = d
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return mutate


MALFORMED = {
    "link_id as string": _set(("ap", "links", 0, "link_id"), "0"),
    "link_id as bool": _set(("ap", "links", 0, "link_id"), True),
    "link_id out of range": _set(("ap", "links", 1, "link_id"), 15),
    "negative link_id": _set(("ap", "links", 0, "link_id"), -1),
    "duplicate link_id": _set(("ap", "links", 1, "link_id"), 0),
    "channel not used in tests": _set(("ap", "links", 0, "channel"), 11),
    "channel as bool": _set(("ap", "links", 0, "channel"), True),
    "unknown AKM": _set(("sta", "akms"), ["WEP"]),
    "empty AKM list": _set(("sta", "akms"), []),
    "repeated AKM": _set(("ap", "links", 0, "akms"), ["SAE", "SAE"]),
    "PMF disabled (not used in MLD tests)": _set(("ap", "pmf"), "disabled"),
    "PMF as hostapd number": _set(("ap", "pmf"), 2),
    "beacon_protection as int": _set(("ap", "beacon_protection"), 1),
    "SAE PWE hunting-and-pecking (not used in tests)": _set(("ap", "sae_pwe"), "hunting_and_pecking"),
    "zero rekey interval": _set(("ap", "gtk_rekey_interval_s"), 0),
    "rekey interval as string": _set(("ap", "ptk_rekey_interval_s"), "5"),
    "unknown SAE group": _set(("sta", "sae_groups"), [1]),
    "repeated SAE group": _set(("sta", "sae_groups"), [19, 19]),
    "unknown pairwise cipher": _set(("ap", "links", 0, "pairwise_cipher"), "TKIP"),
    "raw hostapd option": _set(("ap", "wpa_key_mgmt"), "SAE"),
    "unknown top-level field": _set(("extra",), 1),
    "no links": _set(("ap", "links"), []),
    "missing sta": _delete(("sta",)),
    "missing channel": _delete(("ap", "links", 0, "channel")),
}


@pytest.mark.parametrize("label", MALFORMED)
def test_rejects_malformed(label):
    candidate = copy.deepcopy(BASE)
    MALFORMED[label](candidate)
    with pytest.raises(ValidationError):
        Config.model_validate(candidate)


def test_config_is_immutable():
    config = Config.model_validate(BASE)
    with pytest.raises(ValidationError):
        config.ap.pmf = "optional"


# --- P1 rule violations are NOT rejected here ---------------------------------
# These are well formed; whether they make sense for Wi-Fi is for the P1 rule checker.

P1_NOT_P0 = {
    "SAE PWE set with OWE": {
        "ap": _two_links(["OWE"], sae_pwe="hash_to_element"), "sta": {"akms": ["OWE"]}},
    "client AKM not offered by the AP": {
        "ap": _two_links(["OWE"]), "sta": {"akms": ["SAE"]}},
    "links advertise different AKMs": {
        "ap": {"links": [{"link_id": 0, "channel": 1, "akms": ["WPA-PSK"]},
                         {"link_id": 1, "channel": 6, "akms": ["SAE"]}]},
        "sta": {"akms": ["SAE"]}},
    "SAE PWE set with WPA-PSK only": {
        "ap": _two_links(["WPA-PSK"], sae_pwe="both"), "sta": {"akms": ["WPA-PSK"]}},
}


@pytest.mark.parametrize("label", P1_NOT_P0)
def test_wifi_rule_questions_are_left_to_p1(label):
    Config.model_validate(P1_NOT_P0[label])
