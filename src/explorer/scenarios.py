"""The configuration and actions each runnable hostap test sets up, as model objects.

Read from ``tests/hwsim/test_eht.py`` at the pinned hostap commit (43ee60e1); line
numbers are given per test. ``eht_mld_ap_wpa2_params()`` defaults to ``mfp="2"``,
``pwe=None`` (sae_pwe unset) and ``beacon_prot="1"``, and every two-link test puts
link 0 on channel 1 and link 1 on channel 6.

``TEST_CONFIGS`` lets the P1 checks judge a hostap test before it runs.
``TEST_CANDIDATES`` adds the actions each test performs, in order, so the P2 support
check can tell which test, if any, executes a candidate exactly. Traffic tests,
waits and the legacy ``dev[0]`` client some tests also connect aren't modeled.

Only ``eht_mld_sae_two_links`` turns on the client's beacon protection (715), so the other
tests are recorded with it off and break SEC.EHT_BEACON_PROT. The ``_client_bp`` tests are
our wrappers around them with it on (``docker/test_eht_client_bp.py``).
"""

from __future__ import annotations

from explorer.model import Candidate, Config


def _two_links(akms, *, link1=None, **ap):
    return {"links": [{"link_id": 0, "channel": 1, "akms": akms},
                      {"link_id": 1, "channel": 6, "akms": akms, **(link1 or {})}], **ap}


_REKEY_AKMS = ["SAE-EXT-KEY", "SAE", "WPA-PSK", "WPA-PSK-SHA256"]

TEST_CONFIGS: dict[str, Config] = {name: Config.model_validate(raw) for name, raw in {
    # run_eht_mld_sae_two_links: AP key_mgmt SAE, mfp 2, pwe 1 (692-699);
    # STA sae_pwe 1, sae_groups "20 19", key_mgmt SAE (707-714)
    "eht_mld_sae_two_links": {
        "ap": _two_links(["SAE"], sae_pwe="hash_to_element"),
        "sta": {"akms": ["SAE"], "sae_groups": [20, 19]},
    },
    # test_eht_mld_sae_ext_two_links: AP key_mgmt SAE-EXT-KEY (817-824);
    # STA key_mgmt SAE-EXT-KEY (826). The STA's sae_pwe isn't set here, unlike
    # the fixed hash-to-element STA explorer.model assumes.
    "eht_mld_sae_ext_two_links": {
        "ap": _two_links(["SAE-EXT-KEY"]),
        "sta": {"akms": ["SAE-EXT-KEY"], "beacon_protection": False},
    },
    # _eht_mld_owe_two_links: AP key_mgmt OWE, mfp 2 (502); STA key_mgmt OWE (522)
    "eht_mld_owe_two_links": {
        "ap": _two_links(["OWE"]),
        "sta": {"akms": ["OWE"], "beacon_protection": False},
    },
    # Same helper with second_link_disabled: mld_indicate_disabled 1 on link 1 (510)
    "eht_mld_owe_two_links_one_disabled": {
        "ap": _two_links(["OWE"], link1={"indicate_disabled": True}),
        "sta": {"akms": ["OWE"], "beacon_protection": False},
    },
    # test_eht_mld_ptk_rekey: mixed AKM list, mfp 1 (917-919), wpa_ptk_rekey 5 (920);
    # STA key_mgmt SAE-EXT-KEY (928)
    "eht_mld_ptk_rekey": {
        "ap": _two_links(_REKEY_AKMS, pmf="optional", ptk_rekey_interval_s=5),
        "sta": {"akms": ["SAE-EXT-KEY"], "beacon_protection": False},
    },
    # test_eht_mld_gtk_rekey: same, wpa_group_rekey 5 (958-961); STA (969)
    "eht_mld_gtk_rekey": {
        "ap": _two_links(_REKEY_AKMS, pmf="optional", gtk_rekey_interval_s=5),
        "sta": {"akms": ["SAE-EXT-KEY"], "beacon_protection": False},
    },
    # test_eht_mld_link_removal: AP key_mgmt OWE, mfp 2 (1386); STA OWE (1392).
    # The LINK_REMOVE / REKEY_GTK actions aren't modeled.
    "eht_mld_link_removal": {
        "ap": _two_links(["OWE"]),
        "sta": {"akms": ["OWE"], "beacon_protection": False},
    },
    # test_eht_mld_bss_trans_mgmt_link_removal_imminent: OWE, mfp 2, bss_transition 1 and
    # mbo 1 (1436-1439; mbo isn't modeled); STA OWE (1446). No committed run yet.
    "eht_mld_bss_trans_mgmt_link_removal_imminent": {
        "ap": _two_links(["OWE"], bss_transition=True),
        "sta": {"akms": ["OWE"], "beacon_protection": False},
    },
}.items()}

CLIENT_BP_SUFFIX = "_client_bp"

TEST_CONFIGS |= {
    name + CLIENT_BP_SUFFIX: TEST_CONFIGS[name].model_copy(update={
        "sta": TEST_CONFIGS[name].sta.model_copy(update={"beacon_protection": True})})
    for name in ("eht_mld_sae_ext_two_links", "eht_mld_owe_two_links",
                 "eht_mld_owe_two_links_one_disabled", "eht_mld_ptk_rekey",
                 "eht_mld_gtk_rekey", "eht_mld_link_removal")
}

_ASSOC = {"action": "associate"}
_DISCONNECT = {"action": "sta_disconnect_reconnect", "command": "DISCONNECT"}

# The MLD client's actions in each test, in order. The PTK/GTK rekeys in the rekey tests
# come from the AP's rekey interval, not from an action.
_TEST_ACTIONS = {
    "eht_mld_sae_two_links": [_ASSOC],                          # connect 714
    "eht_mld_sae_ext_two_links": [_ASSOC],                      # connect 826
    # _eht_mld_owe_two_links: connect 522, then DISCONNECT 557-558 (not wait_for_timeout)
    "eht_mld_owe_two_links": [_ASSOC, _DISCONNECT],
    "eht_mld_owe_two_links_one_disabled": [_ASSOC, _DISCONNECT],
    "eht_mld_ptk_rekey": [_ASSOC],                              # connect 928
    "eht_mld_gtk_rekey": [_ASSOC],                              # connect 969
    # connect 1392, LINK_REMOVE 4 on link 1 (1400), REKEY_GTK (1406), LINK_REMOVE 20 on
    # link 0 (1416)
    "eht_mld_link_removal": [
        _ASSOC, {"action": "link_remove", "link_id": 1, "count": 4},
        {"action": "rekey_gtk_now"}, {"action": "link_remove", "link_id": 0, "count": 20}],
    # connect 1447, BSS_TM_REQ with link_removal_imminent=1 (1457-1458)
    "eht_mld_bss_trans_mgmt_link_removal_imminent": [
        _ASSOC, {"action": "bss_tm_link_removal_imminent"}],
}


def _actions(name: str) -> list:
    return _TEST_ACTIONS[name.removesuffix(CLIENT_BP_SUFFIX)]


TEST_CANDIDATES: dict[str, Candidate] = {
    name: Candidate.model_validate({"config": config, "actions": _actions(name)})
    for name, config in TEST_CONFIGS.items()
}
